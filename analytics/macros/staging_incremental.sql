{% macro get_model_meta(model_name) %}
    {% set metadata = var('incremental_model_meta', {}) %}
    {% if model_name not in metadata %}
        {{ exceptions.raise_compiler_error('No incremental metadata found for ' ~ model_name) }}
    {% endif %}
    {{ return(metadata[model_name]) }}
{% endmacro %}

{% macro model_business_keys(model_name) %}
    {% set keys = var('staging_business_keys', {}).get(model_name) %}
    {% if not keys %}
        {{ exceptions.raise_compiler_error('Missing business_key metadata for ' ~ model_name) }}
    {% endif %}
    {{ return(keys) }}
{% endmacro %}

{% macro ensure_scd2_sequence() %}
    create sequence if not exists {{ this.schema }}.{{ this.identifier }}_sk_seq
{% endmacro %}

{% macro scd2_dimension_rows(snapshot_model, sk_column, business_key) %}
    {{ config(indexes=[
        {'columns': [sk_column], 'unique': true},
        {'columns': ['_dimension_version_id'], 'unique': true},
        {'columns': [business_key, '_valid_from', '_valid_to']}
    ]) }}
    with snapshot_rows as (
        select
            snapshot_source.*,
            -- Backfill business events can predate the first database audit
            -- timestamp. Assume the first observed state for that unknown
            -- period; keep dbt_valid_from separately as _observed_from.
            case
                when dbt_valid_from = min(dbt_valid_from) over (partition by {{ business_key }})
                    then '-infinity'::timestamptz
                else dbt_valid_from
            end as _effective_valid_from
        from {{ ref(snapshot_model) }} snapshot_source
    ),
    existing_rows as (
        {% if is_incremental() %}
        select
            _dimension_version_id,
            {{ sk_column }},
            _valid_to
        from {{ this }}
        {% else %}
        select
            null::text as _dimension_version_id,
            null::bigint as {{ sk_column }},
            null::timestamptz as _valid_to
        where false
        {% endif %}
    ),
    changed_rows as (
        select
            snapshot_rows.*,
            coalesce(
                existing_rows.{{ sk_column }},
                nextval('{{ this.schema }}.{{ this.identifier }}_sk_seq'::regclass)
            ) as {{ sk_column }}
        from snapshot_rows
        left join existing_rows
            on existing_rows._dimension_version_id = snapshot_rows.dbt_scd_id
        {% if is_incremental() %}
        where existing_rows._dimension_version_id is null
           or existing_rows._valid_to is distinct from snapshot_rows.dbt_valid_to
        {% endif %}
    )
    select *
    from changed_rows
{% endmacro %}

{% macro is_scd2_dimension_model(model_name) %}
    {{ return(model_name in var('scd2_dimension_models', [])) }}
{% endmacro %}

{% macro latest_source_rows(model_name, include_deleted=false) %}
    {% set keys = model_business_keys(model_name) %}
    (
        select latest.*
        from (
            select distinct on (
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            ) source_row.*
            from {{ ref(model_name) }} as source_row
            order by
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %},
                source_row._source_last_updated_at desc,
                source_row._ingested_at desc,
                source_row._batch_id desc
        ) as latest
        {% if not include_deleted %}
        where not latest._is_deleted
        {% endif %}
    )
{% endmacro %}

{% macro source_incremental(source_name, table_name) %}
{% set keys = model_business_keys(model.name) %}
{% set lookback_hours = var('staging_lookback_hours', 48) | int %}
{% if lookback_hours < 1 %}
    {{ exceptions.raise_compiler_error('staging_lookback_hours must be at least 1') }}
{% endif %}
{{ config(indexes=[
    {'columns': keys + ['_source_last_updated_at'], 'unique': true},
    {'columns': ['_source_last_updated_at']},
    {'columns': ['_ingested_at']}
]) }}
select
    source_row.*,
    current_timestamp as _ingested_at,
    '{{ invocation_id }}'::text as _batch_id,
    source_row._last_updated_at as _source_last_updated_at
from {{ source(source_name, table_name) }} as source_row
{% if is_incremental() %}
where source_row._last_updated_at >= coalesce(
    (
        select max(_source_last_updated_at)
        from {{ this }}
    ),
    '1900-01-01'::timestamptz
) - interval '{{ lookback_hours }} hours'
and not exists (
    select 1
    from {{ this }} loaded
    where {% for key in keys %}
        loaded.{{ key }} = source_row.{{ key }} and
    {% endfor %}
        loaded._source_last_updated_at = source_row._last_updated_at
)
{% endif %}
{% endmacro %}

{% macro core_source_rows(source_model, target_model) %}
    {% set keys = model_business_keys(source_model) %}
    {% set meta = get_model_meta(target_model) %}
    {% set dependencies = meta.get('dependencies', []) %}
    {{ config(indexes=[
        {'columns': keys, 'unique': true},
        {'columns': ['_source_ingested_at']},
        {'columns': ['_record_updated_at']}
    ]) }}
    {% if not is_incremental() %}
        {{ latest_source_rows(source_model, true) }}
    {% else %}
        with target_watermark as (
            select coalesce(
                max(_source_ingested_at),
                '1900-01-01'::timestamptz
            ) as watermark
            from {{ this }}
        ),
        candidate_keys as (
            select distinct
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            from {{ ref(source_model) }} as source_row
            cross join target_watermark
            where source_row._ingested_at > target_watermark.watermark
            {% for dependency in dependencies %}
            union
            select distinct
                {% for key in keys %}
                target_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            from {{ this }} as target_row
            join {{ ref(dependency['model']) }} as dependency_row
              on {% for index in range(dependency['parent_key'] | length) %}
                 target_row.{{ dependency['child_key'][index] }} = dependency_row.{{ dependency['parent_key'][index] }}{% if not loop.last %} and {% endif %}
                 {% endfor %}
            {% if is_scd2_dimension_model(dependency['model']) %}
            where dependency_row._is_current
            {% endif %}
            {% if is_scd2_dimension_model(dependency['model']) %}
              and dependency_row._record_updated_at > target_row._record_updated_at
            {% else %}
            where dependency_row._record_updated_at > target_row._record_updated_at
            {% endif %}
            {% endfor %}
        ),
        latest as (
            select distinct on (
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            ) source_row.*
            from {{ ref(source_model) }} as source_row
            join candidate_keys
              on {% for key in keys %}
                 source_row.{{ key }} = candidate_keys.{{ key }}{% if not loop.last %} and {% endif %}
                 {% endfor %}
            order by
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %},
                source_row._source_last_updated_at desc,
                source_row._ingested_at desc,
                source_row._batch_id desc
        )
        select * from latest
    {% endif %}
{% endmacro %}

{% macro core_partition_source_rows(source_model, target_model) %}
    {% set keys = model_business_keys(source_model) %}
    {% set meta = get_model_meta(target_model) %}
    {% set partition_keys = meta.get('partition_key', []) %}
    {% set dependencies = meta.get('dependencies', []) %}
    {{ config(indexes=[
        {'columns': keys, 'unique': true},
        {'columns': partition_keys},
        {'columns': ['_source_ingested_at']},
        {'columns': ['_record_updated_at']}
    ]) }}
    {% if not partition_keys %}
        {{ exceptions.raise_compiler_error('Missing partition_key metadata for ' ~ target_model) }}
    {% endif %}
    {% if not is_incremental() %}
        select
            source_row.*,
            null::timestamptz as _partition_recomputed_at
        from {{ latest_source_rows(source_model, true) }} as source_row
    {% else %}
        with target_watermark as (
            select coalesce(
                max(_source_ingested_at),
                '1900-01-01'::timestamptz
            ) as watermark
            from {{ this }}
        ),
        changed_source_keys as (
            select distinct
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            from {{ ref(source_model) }} as source_row
            cross join target_watermark
            where source_row._ingested_at > target_watermark.watermark
        ),
        changed_partitions as (
            select distinct
                {% for key in partition_keys %}
                source_history.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %},
                current_timestamp as partition_recomputed_at
            from {{ ref(source_model) }} as source_history
            join changed_source_keys
              on {% for key in keys %}
                 source_history.{{ key }} is not distinct from changed_source_keys.{{ key }}{% if not loop.last %} and {% endif %}
                 {% endfor %}
            {% for dependency in dependencies %}
            union
            select distinct
                {% for key in partition_keys %}
                target_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %},
                current_timestamp as partition_recomputed_at
            from {{ this }} as target_row
            join {{ ref(dependency['model']) }} as dependency_row
              on {% for index in range(dependency['parent_key'] | length) %}
                 target_row.{{ dependency['child_key'][index] }} = dependency_row.{{ dependency['parent_key'][index] }}{% if not loop.last %} and {% endif %}
                 {% endfor %}
            {% if is_scd2_dimension_model(dependency['model']) %}
            where dependency_row._is_current
              and dependency_row._record_updated_at > target_row._record_updated_at
            {% else %}
            where dependency_row._record_updated_at > target_row._record_updated_at
            {% endif %}
            {% endfor %}
        ),
        latest as (
            select distinct on (
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %}
            )
                source_row.*,
                changed_partitions.partition_recomputed_at as _partition_recomputed_at
            from {{ ref(source_model) }} as source_row
            join changed_partitions
              on {% for key in partition_keys %}
                 source_row.{{ key }} is not distinct from changed_partitions.{{ key }}{% if not loop.last %} and {% endif %}
                 {% endfor %}
            order by
                {% for key in keys %}
                source_row.{{ key }}{% if not loop.last %}, {% endif %}
                {% endfor %},
                source_row._source_last_updated_at desc,
                source_row._ingested_at desc,
                source_row._batch_id desc
        )
        select * from latest
    {% endif %}
{% endmacro %}

{% macro core_metadata_columns(source_alias, dependency_aliases=[]) %}
    , {{ source_alias }}._source_last_updated_at
    , {{ source_alias }}._ingested_at as _source_ingested_at
    , greatest(
        {{ source_alias }}._ingested_at
        {% for dependency_alias in dependency_aliases %}
        , coalesce({{ dependency_alias }}._record_updated_at, {{ source_alias }}._ingested_at)
        {% endfor %}
      ) as _record_updated_at
{% endmacro %}

{% macro changed_keys_with_watermark(key, upstream_models) %}
    select
        changed.{{ key }},
        max(changed.changed_record_updated_at) as changed_record_updated_at
    from (
        {% for upstream_model in upstream_models %}
        select
            {{ key }},
            _record_updated_at as changed_record_updated_at
        from {{ ref(upstream_model) }}
        where _record_updated_at > coalesce(
            (select max(_record_updated_at) from {{ this }}),
            '1900-01-01'::timestamptz
        )
        {% if not loop.last %}union all{% endif %}
        {% endfor %}
    ) as changed
    group by changed.{{ key }}
{% endmacro %}

{% macro mart_model_meta(model_name) %}
    {% set metadata = var('mart_model_meta', {}) %}
    {% if model_name not in metadata %}
        {{ exceptions.raise_compiler_error('No mart incremental metadata found for ' ~ model_name) }}
    {% endif %}
    {{ return(metadata[model_name]) }}
{% endmacro %}

{% macro mart_changed_keys(model_name) %}
    {% set meta = mart_model_meta(model_name) %}
    {% set keys = meta['key'] %}
    {% set upstreams = meta['upstream'] %}
    {% if not is_incremental() %}
        {% for upstream in upstreams %}
        select distinct
            {% for key in keys %}
            upstream_row.{{ key }}{% if not loop.last %}, {% endif %}
            {% endfor %}
        from {{ ref(upstream['model']) }} upstream_row
        {% if not loop.last %}union{% endif %}
        {% endfor %}
    {% else %}
        {% for upstream in upstreams %}
        select distinct
            {% for key in keys %}
            upstream_row.{{ key }}{% if not loop.last %}, {% endif %}
            {% endfor %}
        from {{ ref(upstream['model']) }} upstream_row
        where upstream_row._record_updated_at > coalesce(
            (select max(_record_updated_at) from {{ this }}),
            '1900-01-01'::timestamptz
        )
        {% if not loop.last %}union{% endif %}
        {% endfor %}
    {% endif %}
{% endmacro %}

{% macro delete_affected_mart_rows(model_name) %}
    {% if not is_incremental() %}
        select 1
    {% else %}
        {% set meta = mart_model_meta(model_name) %}
        {% set keys = meta['key'] %}
        delete from {{ this }} as target_row
        using (
            {{ mart_changed_keys(model_name) }}
        ) as changed_keys
        where {% for key in keys %}
            target_row.{{ key }} is not distinct from changed_keys.{{ key }}{% if not loop.last %} and {% endif %}
            {% endfor %}
    {% endif %}
{% endmacro %}

{% macro refresh_inventory_position_as_of_run() %}
    update {{ this }}
    set
        as_of_date = current_date,
        available_quantity = case
            when expires_at is not null and expires_at < current_date then 0::numeric
            else greatest(on_hand_quantity, 0)::numeric
        end,
        is_expired_as_of_run = expires_at is not null and expires_at < current_date
{% endmacro %}

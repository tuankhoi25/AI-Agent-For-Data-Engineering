{% macro postgres__snapshot_get_time() -%}
    {# Match the source audit TIMESTAMPTZ contract, including soft-deletion time. #}
    current_timestamp::timestamptz
{%- endmacro %}

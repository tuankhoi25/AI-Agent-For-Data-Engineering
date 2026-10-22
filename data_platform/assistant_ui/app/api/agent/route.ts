export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const response = await fetch(process.env.BAKERY_AGENT_URL ?? "http://bakery_agent:8123/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: await request.text(),
      signal: request.signal,
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json({ error: "Could not reach the Bakery agent." }, { status: 502 });
  }
}

import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
const paths = new Set(["health", "login", "session", "mutation", "logout"]);

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path.length !== 1 || !paths.has(path[0])) return new Response(null, { status: 404 });
  const headers = new Headers();
  for (const name of ["cookie", "content-type", "origin"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const upstream = await fetch(`${process.env.S0_API_ORIGIN}/api/spike/${path[0]}`, {
    method: request.method,
    headers,
    body: request.method === "GET" ? undefined : await request.text(),
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = new Headers({ "Cache-Control": "private, no-store" });
  const contentType = upstream.headers.get("content-type");
  if (contentType) responseHeaders.set("content-type", contentType);
  for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
  return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;

import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

export default async function Page() {
  const jar = await cookies();
  // Mutation switch is fixture-only and must never enter the product scaffold.
  const cookie = process.env.S0_DROP_SSR_COOKIE === "1" ? "" : jar.toString();
  const response = await fetch(`${process.env.S0_API_ORIGIN}/api/spike/session`, {
    headers: cookie ? { Cookie: cookie } : {},
    cache: "no-store",
  });
  const actor = response.ok ? await response.json() as { id: string; name: string } : null;
  return <main><h1>S0 登入拓樸實驗</h1><p data-identity={actor?.name ?? "anonymous"}>
    {actor ? `${actor.name} (${actor.id})` : "anonymous"}
  </p></main>;
}

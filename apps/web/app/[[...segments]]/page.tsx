import { cookies } from "next/headers";
import Workspace from "../../components/workspace";

export const dynamic = "force-dynamic";

export default async function Page({
  params,
}: {
  params: Promise<{ segments?: string[] }>;
}) {
  const { segments = [] } = await params;
  const jar = await cookies();
  let initial: Record<string, unknown> = {};
  if (jar.size) {
    try {
      const response = await fetch(
        (process.env.API_ORIGIN || "http://127.0.0.1:18000") +
          "/api/v1/auth/session",
        {
          headers: { Cookie: jar.toString() },
          cache: "no-store",
          signal: AbortSignal.timeout(5000),
        },
      );
      if (response.ok) initial.session = await response.json();
    } catch {
      /* Client retries authentication. */
    }
  }
  if (segments[0] === "question" && /^[1-9][0-9]*$/.test(segments[1] || "")) {
    try {
      const response = await fetch(
        (process.env.API_ORIGIN || "http://127.0.0.1:18000") +
          "/api/v1/questions/" +
          segments[1],
        {
          headers: { Cookie: jar.toString() },
          cache: "no-store",
          signal: AbortSignal.timeout(5000),
        },
      );
      if (response.ok) initial.question = await response.json();
    } catch {
      /* Client retries the question request. */
    }
  }
  if (segments.length === 0 || segments[0] === "banks") {
    const paths = segments.length === 0 ? ["banks", "questions"] : ["banks"];
    for (const path of paths) {
      try {
        const response = await fetch(
          `${process.env.API_ORIGIN || "http://127.0.0.1:18000"}/api/v1/${path}`,
          {
            headers: { Cookie: jar.toString() },
            cache: "no-store",
            signal: AbortSignal.timeout(5000),
          },
        );
        if (response.ok) initial[path] = await response.json();
      } catch {
        /* Client displays the concrete service error on retry. */
      }
    }
  }
  return <Workspace route={segments} initial={initial} />;
}

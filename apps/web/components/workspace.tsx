"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { components } from "../../../packages/api-client/schema";
import contract from "../../../packages/api-client/openapi.json";

type Bank = components["schemas"]["BankView"];
type Question = components["schemas"]["QuestionView"];
type User = components["schemas"]["SessionView"];
type Interview = components["schemas"]["InterviewView"];
type Job = components["schemas"]["JobView"];
type Page<T> = Omit<
  components["schemas"]["PageView_QuestionView_"],
  "items"
> & { items: T[] };
type Navigation = components["schemas"]["NavigationView"];
type Json = Record<string, unknown>;
type Action = (fn: () => Promise<void>) => Promise<void>;
const roleOptions = contract.components.schemas.AdminUser.properties.role.enum;
const reviewOptions =
  contract.components.schemas.QuestionInput.properties.review_status.enum;
const friendly: Record<string, string> = {
  authentication_required: "請先登入",
  session_expired: "登入逾時，請重新登入",
  invalid_credentials: "帳號或密碼不正確",
  account_exists: "帳號已註冊",
  password_mismatch: "兩次密碼不一致",
  administrator_required: "需要管理員權限",
  csrf_denied: "驗證已更新，請重新整理",
  version_conflict: "資料已更新，請重新載入",
  provider_unavailable: "面試服務暫時無法回應，目前進度已保留",
  search_unavailable: "搜尋服務暫時無法使用",
  invalid_transition: "目前面試狀態無法執行此操作",
  history_limit: "本次面試已達長度上限，請結束面試",
  event_in_progress: "上一則回應正在產生",
  api_unavailable: "服務暫時無法連線",
  not_found: "找不到資料",
  dependency_unavailable: "服務依賴暫時無法使用，請稍後重試",
  context_limit: "本次面試已達模型上下文上限，請結束面試取得總結",
  crawl_cooldown: "讀取過於頻繁，請稍候再試",
  validation_failed: "請確認輸入內容符合要求",
};
async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  csrf?: string,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ code: "api_unavailable" }));
    throw new Error(friendly[error.code] || error.detail || "操作失敗");
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
function Pagination({
  page,
  total,
  onPage,
}: {
  page: number;
  total: number;
  onPage: (n: number) => void;
}) {
  return (
    <div className="pagination">
      <button
        className="secondary"
        disabled={page === 1}
        onClick={() => onPage(page - 1)}
      >
        上一頁
      </button>
      <span className="muted">
        第 {page} 頁 · 共 {total} 筆
      </span>
      <button
        className="secondary"
        disabled={page * 20 >= total}
        onClick={() => onPage(page + 1)}
      >
        下一頁
      </button>
    </div>
  );
}
function SafeMarkdown({ value }: { value: string }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{value}</Markdown>
    </div>
  );
}
function imageUrl(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}

export default function Workspace({
  route,
  initial,
}: {
  route: string[];
  initial: Record<string, unknown>;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(
    (initial.session as User | undefined) || null,
  );
  const [loaded, setLoaded] = useState("session" in initial);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const pendingActions = useRef(0);
  const path = "/" + route.join("/");
  const refresh = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/session"));
    } catch {
      setUser(null);
    } finally {
      setLoaded(true);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    setError("");
    setSuccess("");
  }, [path]);
  const action: Action = async (fn) => {
    pendingActions.current++;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      pendingActions.current--;
      setBusy(pendingActions.current > 0);
    }
  };
  const nav = [
    ["/", "學習首頁"],
    ["/banks", "探索題庫"],
    ["/questions", "搜尋題目"],
    ["/mockInterview", "模擬面試"],
    ["/user/center", "我的學習"],
  ];
  return (
    <>
      <header>
        <Link href="/" className="logo">
          <b>面試</b>練習室 <span className="small">/ STUDY ROOM</span>
        </Link>
        <nav>
          <Link href="/banks">題庫</Link>
          <Link href="/mockInterview">模擬面試</Link>
          {user ? (
            <>
              <Link href="/user/center" className="row">
                <span className="avatar">
                  {user.name.slice(0, 1)}
                  {imageUrl(user.avatar_url) && (
                    <img
                      key={user.avatar_url}
                      src={imageUrl(user.avatar_url)}
                      alt=""
                      referrerPolicy="no-referrer"
                      onError={(e) => {
                        e.currentTarget.hidden = true;
                      }}
                    />
                  )}
                </span>
                {user.name}
              </Link>
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await api(
                      "/auth/session",
                      "DELETE",
                      undefined,
                      user.csrf_token,
                    );
                    setUser(null);
                    router.push("/");
                  })
                }
              >
                登出
              </button>
            </>
          ) : (
            <Link className="button" href="/user/login">
              登入 / 註冊
            </Link>
          )}
        </nav>
      </header>
      <div className="shell">
        <aside>
          {nav.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={path === href ? "active" : ""}
            >
              {label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <>
              <p className="eyebrow">管理工作區</p>
              {[
                ["user", "使用者"],
                ["questionBank", "題庫管理"],
                ["question", "題目管理"],
                ["question/ai", "AI 出題"],
                ["interviews", "面試紀錄"],
                ["policies", "服務政策"],
              ].map(([p, l]) => (
                <Link
                  key={p}
                  href={"/admin/" + p}
                  className={path === "/admin/" + p ? "active" : ""}
                >
                  {l}
                </Link>
              ))}
            </>
          )}
          <footer>
            每天一題，練習說清楚。
            <br />
            從理解到可以解釋。
          </footer>
        </aside>
        <main className="content">
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {success && (
            <div className="success" role="status">
              {success}
            </div>
          )}
          {route[0] === "admin" ? (
            !loaded ? (
              <p className="loading">確認權限中…</p>
            ) : user?.role !== "admin" ? (
              <div className="panel">
                <h1>管理工作區</h1>
                <p>需要管理員權限。</p>
                <Link className="button" href="/user/login">
                  前往登入
                </Link>
              </div>
            ) : (
              <Admin
                route={route.slice(1)}
                user={user}
                action={action}
                busy={busy}
                report={setSuccess}
              />
            )
          ) : route[0] === "user" &&
            ["login", "register"].includes(route[1]) ? (
            <Auth
              register={route[1] === "register"}
              action={action}
              busy={busy}
              refresh={refresh}
            />
          ) : path === "/user/center" ? (
            <Profile
              user={user}
              loaded={loaded}
              action={action}
              busy={busy}
              report={setSuccess}
              refresh={refresh}
            />
          ) : route[0] === "mockInterview" ? (
            <Interviews
              route={route.slice(1)}
              user={user}
              loaded={loaded}
              action={action}
              busy={busy}
            />
          ) : route[0] === "bank" && route[1] ? (
            <BankDetail
              id={route[1]}
              questionId={route[2] === "question" ? route[3] : undefined}
              action={action}
            />
          ) : route[0] === "question" && route[1] ? (
            <QuestionDetail
              id={route[1]}
              action={action}
              initial={initial.question as Question | undefined}
            />
          ) : path === "/questions" ? (
            <Questions action={action} />
          ) : path === "/banks" ? (
            <Banks
              initial={initial.banks as Page<Bank> | undefined}
              action={action}
            />
          ) : path === "/" ? (
            <Home initial={initial} action={action} />
          ) : (
            <div className="panel">
              <h1>頁面不存在</h1>
              <Link href="/">回首頁</Link>
            </div>
          )}
        </main>
      </div>
    </>
  );
}

function BankCard({ bank, index }: { bank: Bank; index: number }) {
  return (
    <Link href={"/bank/" + bank.id} className="card">
      {imageUrl(bank.picture_url) && (
        <img
          key={bank.picture_url}
          className="bank-picture"
          src={imageUrl(bank.picture_url)}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={(e) => {
            e.currentTarget.hidden = true;
          }}
        />
      )}
      <span className="number">
        CHAPTER {String(index + 1).padStart(2, "0")}
      </span>
      <h3>{bank.title}</h3>
      <p>{bank.description || "整理核心問題，循序練習。"}</p>
      <span className="muted">進入題庫 ↗</span>
    </Link>
  );
}
function Author({
  author,
}: {
  author?: components["schemas"]["UserView"] | null;
}) {
  return author ? <p className="muted">作者：{author.name}</p> : null;
}
function QuestionRow({
  question,
  href,
}: {
  question: Question;
  href?: string;
}) {
  return (
    <div className="list-item">
      <div>
        <Link href={href || "/question/" + question.id}>
          <h3>{question.title}</h3>
        </Link>
        {question.tags.map((t) => (
          <span className="tag" key={t}>
            {t}
          </span>
        ))}
        <Author author={question.author} />
      </div>
      <Link
        aria-label={"練習 " + question.title}
        href={href || "/question/" + question.id}
      >
        ↗
      </Link>
    </div>
  );
}
function Home({
  initial,
  action,
}: {
  initial: Record<string, unknown>;
  action: Action;
}) {
  const [banks, setBanks] = useState(initial.banks as Page<Bank> | undefined);
  const [questions, setQuestions] = useState(
    initial.questions as Page<Question> | undefined,
  );
  useEffect(() => {
    if (!banks || !questions)
      void action(async () => {
        const [b, q] = await Promise.all([
          api<Page<Bank>>("/banks"),
          api<Page<Question>>("/questions"),
        ]);
        setBanks(b);
        setQuestions(q);
      });
  }, []);
  return (
    <>
      <div className="hero">
        <div>
          <span className="eyebrow">A LITTLE PRACTICE, EVERY DAY</span>
          <h1>
            把每一道題，
            <br />
            變成你說得清楚的知識。
          </h1>
          <p>
            從主題題庫開始，理解答案、練習表達。
            <br />
            準備好了，再用模擬面試檢查自己的思路。
          </p>
          <div className="actions">
            <Link href="/banks" className="button">
              開始練習 ↗
            </Link>
            <Link href="/mockInterview/add" className="button secondary">
              模擬面試
            </Link>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          ↗
        </div>
      </div>
      <div className="section-title">
        <h2>選一個主題，開始深入</h2>
        <Link href="/banks">全部題庫 →</Link>
      </div>
      <div className="grid">
        {banks?.items.slice(0, 6).map((b, i) => (
          <BankCard key={b.id} bank={b} index={i} />
        ))}
      </div>
      <div className="section-title">
        <h2>今日練習靈感</h2>
        <Link href="/questions">搜尋題目 →</Link>
      </div>
      <div className="panel">
        {questions?.items.slice(0, 5).map((q) => (
          <QuestionRow key={q.id} question={q} />
        ))}
        {questions?.total === 0 && (
          <p className="empty">題目即將加入，先建立你的學習帳號。</p>
        )}
      </div>
    </>
  );
}
function Banks({ initial, action }: { initial?: Page<Bank>; action: Action }) {
  const [data, setData] = useState(initial);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const load = (p = page) =>
    action(async () => {
      setData(
        await api<Page<Bank>>(
          "/banks?page=" + p + "&q=" + encodeURIComponent(q),
        ),
      );
      setPage(p);
    });
  useEffect(() => {
    if (!initial) void load(1);
  }, []);
  return (
    <>
      <span className="eyebrow">QUESTION BANKS</span>
      <h1>探索題庫</h1>
      <p className="muted">按主題整理，找到適合你的下一步。</p>
      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          void load(1);
        }}
      >
        <input
          aria-label="搜尋題庫"
          placeholder="搜尋題庫名稱"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button>搜尋</button>
      </form>
      <div className="grid">
        {data?.items.map((b, i) => (
          <BankCard key={b.id} bank={b} index={i} />
        ))}
      </div>
      {data?.total === 0 && <p className="empty">沒有符合條件的題庫</p>}
      {data && (
        <Pagination
          page={page}
          total={data.total}
          onPage={(p) => void load(p)}
        />
      )}
    </>
  );
}
function Questions({ action }: { action: Action }) {
  const [data, setData] = useState<Page<Question>>();
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [bank, setBank] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("relevance");
  const load = (p = page, full = true) =>
    action(async () => {
      const params = new URLSearchParams({ page: String(p), q });
      for (const t of tag
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean))
        params.append("tags", t);
      if (bank) params.set("bank_id", bank);
      if (full) params.set("sort", sort);
      setData(
        await api<Page<Question>>(
          (full ? "/questions/search?" : "/questions?") + params,
        ),
      );
      setPage(p);
    });
  useEffect(() => {
    void load(1, false);
  }, []);
  return (
    <>
      <span className="eyebrow">FIND YOUR NEXT QUESTION</span>
      <h1>搜尋題目</h1>
      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          void load(1);
        }}
      >
        <input
          aria-label="搜尋題目"
          placeholder="關鍵字：交易、SSR、Python"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <input
          aria-label="標籤"
          placeholder="標籤，以逗號分隔"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
        />
        <input
          aria-label="題庫 ID"
          placeholder="題庫 ID（選填）"
          value={bank}
          onChange={(e) => setBank(e.target.value)}
        />
        <select
          aria-label="排序"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="relevance">相關度</option>
          <option value="create_time">最新加入</option>
          <option value="update_time">最近更新</option>
          <option value="id">編號</option>
        </select>
        <button>搜尋</button>
      </form>
      <div className="panel">
        {data?.items.map((q) => (
          <QuestionRow key={q.id} question={q} />
        ))}
        {data?.items.length === 0 && (
          <p className="empty">没有符合條件的題目，試試其他關鍵字。</p>
        )}
      </div>
      {data && (
        <Pagination
          page={page}
          total={data.total}
          onPage={(p) => void load(p)}
        />
      )}
    </>
  );
}
function QuestionDetail({
  id,
  action,
  initial,
}: {
  id: string;
  action: Action;
  initial?: Question;
}) {
  const [q, setQ] = useState<Question | undefined>(initial);
  const [answer, setAnswer] = useState(false);
  useEffect(() => {
    setAnswer(false);
    if (!initial || initial.id !== id)
      void action(async () => setQ(await api<Question>("/questions/" + id)));
  }, [id]);
  if (!q) return <p className="loading">正在載入題目…</p>;
  return (
    <>
      <span className="eyebrow">QUESTION {q.id}</span>
      <h1>{q.title}</h1>
      <Author author={q.author} />
      <div>
        {q.tags.map((t) => (
          <span key={t} className="tag">
            {t}
          </span>
        ))}
      </div>
      <div className="panel">
        <SafeMarkdown value={q.content} />
      </div>
      <button
        className="answer-toggle secondary"
        aria-expanded={answer}
        onClick={() => setAnswer(!answer)}
      >
        {answer ? "收起題解" : "完成思考，查看題解"}
      </button>
      {answer && (
        <div className="panel">
          <h2>參考題解</h2>
          <SafeMarkdown value={q.answer} />
        </div>
      )}
    </>
  );
}
function BankDetail({
  id,
  questionId,
  action,
}: {
  id: string;
  questionId?: string;
  action: Action;
}) {
  const [bank, setBank] = useState<Bank>();
  const [qs, setQs] = useState<Page<Question>>();
  const [page, setPage] = useState(1);
  const [nav, setNav] = useState<Navigation>();
  const load = (p = 1) =>
    action(async () => {
      const [b, q] = await Promise.all([
        api<Bank>("/banks/" + id),
        api<Page<Question>>("/questions?bank_id=" + id + "&page=" + p),
      ]);
      setBank(b);
      setQs(q);
      setPage(p);
    });
  useEffect(() => {
    if (questionId)
      void action(async () => {
        const n = await api<Navigation>(
          "/banks/" + id + "/questions/" + questionId + "/navigation",
        );
        setNav(n);
        await load(n.page);
      });
    else void load();
  }, [id, questionId]);
  if (questionId)
    return (
      <div className="two-column">
        <nav className="question-nav" aria-label="題庫題目導覽">
          <Link href={"/bank/" + id}>
            <h3>{bank?.title || "題庫導覽"}</h3>
          </Link>
          {!qs && <p className="muted">正在載入題庫題目…</p>}
          {qs?.items.map((q) => (
            <Link key={q.id} href={"/bank/" + id + "/question/" + q.id}>
              {q.title}
            </Link>
          ))}
          {qs && (
            <Pagination
              page={page}
              total={qs.total}
              onPage={(p) => void load(p)}
            />
          )}
        </nav>
        <div>
          <QuestionDetail id={questionId} action={action} />
          <div className="actions">
            {nav?.previous_id && (
              <Link
                className="button secondary"
                href={"/bank/" + id + "/question/" + nav.previous_id}
              >
                上一題
              </Link>
            )}
            {nav?.next_id && (
              <Link
                className="button"
                href={"/bank/" + id + "/question/" + nav.next_id}
              >
                下一題
              </Link>
            )}
          </div>
        </div>
      </div>
    );
  return (
    <>
      <span className="eyebrow">CHAPTER / {id}</span>
      <h1>{bank?.title || "題庫"}</h1>
      <Author author={bank?.author} />
      <p className="muted">{bank?.description}</p>
      <div className="panel">
        {qs?.items.map((q) => (
          <QuestionRow
            key={q.id}
            question={q}
            href={"/bank/" + id + "/question/" + q.id}
          />
        ))}
        {qs?.total === 0 && <p className="empty">這個題庫還沒有題目。</p>}
      </div>
      {qs && (
        <Pagination page={page} total={qs.total} onPage={(p) => void load(p)} />
      )}
    </>
  );
}

function Auth({
  register,
  action,
  busy,
  refresh,
}: {
  register: boolean;
  action: Action;
  busy: boolean;
  refresh: () => Promise<void>;
}) {
  const router = useRouter();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  return (
    <div className="auth panel">
      <span className="eyebrow">WELCOME TO YOUR STUDY ROOM</span>
      <h1>{register ? "建立學習帳號" : "歡迎回來"}</h1>
      <p className="muted">保存練習活動，開始你的面試準備。</p>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          void action(async () => {
            if (register)
              await api("/auth/register", "POST", {
                account,
                password,
                confirmation,
              });
            await api("/auth/sessions", "POST", { account, password });
            await refresh();
            router.push("/user/center");
          });
        }}
      >
        <label>
          <span>帳號</span>
          <input
            required
            minLength={4}
            maxLength={256}
            autoComplete="username"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
          />
        </label>
        <label>
          <span>密碼</span>
          <input
            required
            type="password"
            minLength={8}
            autoComplete={register ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {register && (
          <label>
            <span>再次輸入密碼</span>
            <input
              required
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
          </label>
        )}
        <button disabled={busy}>
          {busy ? "處理中…" : register ? "註冊並開始學習" : "登入"}
        </button>
      </form>
      <p className="muted">
        {register ? "已有帳號？" : "第一次來？"}{" "}
        <Link href={register ? "/user/login" : "/user/register"}>
          {register ? "登入" : "建立帳號"}
        </Link>
      </p>
    </div>
  );
}
function Profile({
  user,
  loaded,
  action,
  busy,
  report,
  refresh,
}: {
  user: User | null;
  loaded: boolean;
  action: Action;
  busy: boolean;
  report: (s: string) => void;
  refresh: () => Promise<void>;
}) {
  const [profile, setProfile] = useState<Record<string, string>>({});
  const [profileReady, setProfileReady] = useState(false);
  const [year, setYear] = useState(new Date().getFullYear());
  const [dates, setDates] = useState<string[]>([]);
  useEffect(() => {
    setProfileReady(false);
    if (user)
      void action(async () => {
        setProfile(await api<Record<string, string>>("/users/me"));
        setProfileReady(true);
      });
  }, [user?.id]);
  useEffect(() => {
    if (user)
      void action(async () => {
        setDates(
          (await api<{ dates: string[] }>("/users/me/activity?year=" + year))
            .dates,
        );
      });
  }, [user?.id, year]);
  if (!loaded) return <p className="loading">正在載入…</p>;
  if (!user)
    return (
      <div className="panel">
        <h1>我的學習</h1>
        <p>登入後保存活動與面試紀錄。</p>
        <Link href="/user/login" className="button">
          前往登入
        </Link>
      </div>
    );
  const days = Array.from(
    { length: new Date(year, 1, 29).getMonth() === 1 ? 366 : 365 },
    (_, i) => new Date(Date.UTC(year, 0, i + 1)).toISOString().slice(0, 10),
  );
  const fields = [
    ["name", "姓名"],
    ["avatar_url", "頭像 URL"],
    ["bio", "自我介紹"],
    ["phone", "電話"],
    ["email", "Email"],
    ["grade", "年級"],
    ["experience", "工作經驗"],
    ["direction", "學習方向"],
  ];
  return (
    <>
      <span className="eyebrow">YOUR LEARNING JOURNEY</span>
      <h1>{user.name} 的學習空間</h1>
      <div className="panel">
        <div className="section-title">
          <h2>閱讀活動 · {dates.length} 天</h2>
          <select
            aria-label="活動年份"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          >
            {Array.from(
              { length: 5 },
              (_, i) => new Date().getFullYear() - 2 + i,
            ).map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </div>
        <div className="heatmap" aria-label="年度閱讀熱力圖">
          {days.map((d) => (
            <div
              key={d}
              className={"day " + (dates.includes(d) ? "filled" : "")}
              title={d + (dates.includes(d) ? " · 已練習" : "")}
            />
          ))}
        </div>
        <p className="muted">成功開啟題目後，自動記錄當天的活動。</p>
      </div>
      <div className="panel">
        <h2>個人資料</h2>
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void action(async () => {
              await api(
                "/users/me",
                "PATCH",
                Object.fromEntries(fields.map(([k]) => [k, profile[k] || ""])),
                user.csrf_token,
              );
              await refresh();
              report("個人資料已保存");
            });
          }}
        >
          {fields.map(([key, label]) => (
            <label key={key}>
              <span>{label}</span>
              <input
                disabled={!profileReady || busy}
                value={profile[key] || ""}
                onChange={(e) =>
                  setProfile({ ...profile, [key]: e.target.value })
                }
              />
            </label>
          ))}
          <button disabled={!profileReady || busy}>保存資料</button>
        </form>
      </div>
    </>
  );
}
function Interviews({
  route,
  user,
  loaded,
  action,
  busy,
}: {
  route: string[];
  user: User | null;
  loaded: boolean;
  action: Action;
  busy: boolean;
}) {
  const router = useRouter();
  const [items, setItems] = useState<Page<Interview>>();
  const [interview, setInterview] = useState<Interview>();
  const [message, setMessage] = useState("");
  const [position, setPosition] = useState("後端工程師");
  const [experience, setExperience] = useState("初階");
  const [difficulty, setDifficulty] = useState("medium");
  const [page, setPage] = useState(1);
  const pendingEvent = useRef<{ signature: string; id: string } | null>(null);
  const id = route[0] === "chat" ? route[1] : undefined;
  const load = (p = 1) =>
    action(async () => {
      setItems(await api<Page<Interview>>("/interviews?page=" + p));
      setPage(p);
    });
  useEffect(() => {
    if (user) {
      if (id)
        void action(async () =>
          setInterview(await api<Interview>("/interviews/" + id)),
        );
      else if (route[0] !== "add") void load();
    }
  }, [user?.id, id, route[0]]);
  if (!loaded) return <p className="loading">正在載入…</p>;
  if (!user)
    return (
      <div className="panel">
        <h1>模擬面試</h1>
        <p>登入後，選擇職位與難度，練習回答及追問。</p>
        <Link href="/user/login" className="button">
          登入開始
        </Link>
      </div>
    );
  const send = (event: "start" | "chat" | "end") =>
    action(async () => {
      const text = event === "chat" ? message : "";
      const signature = JSON.stringify({ event, message: text });
      if (pendingEvent.current?.signature !== signature)
        pendingEvent.current = { signature, id: crypto.randomUUID() };
      setInterview(
        await api<Interview>(
          "/interviews/" + id + "/events",
          "POST",
          { event, event_id: pendingEvent.current.id, message: text },
          user.csrf_token,
        ),
      );
      pendingEvent.current = null;
      setMessage("");
    });
  if (id)
    return (
      <>
        <span className="eyebrow">MOCK INTERVIEW / {interview?.status}</span>
        <h1>{interview?.position || "模擬面試"}</h1>
        <p className="muted">
          {interview?.experience} · {interview?.difficulty}
        </p>
        {interview?.history.map((m, i) => (
          <div className={"message " + m.role} key={i}>
            <div className="label">
              {m.role === "assistant" ? "面試官" : "你的回答"}
            </div>
            <SafeMarkdown value={m.content} />
          </div>
        ))}
        {interview?.status === "NOT_STARTED" ? (
          <button disabled={busy} onClick={() => void send("start")}>
            開始面試
          </button>
        ) : interview?.status === "ACTIVE" ? (
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              void send("chat");
            }}
          >
            <label>
              <span>你的回答</span>
              <textarea
                required
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={10000}
              />
            </label>
            <div className="actions">
              <button disabled={busy}>
                {busy ? "面試官思考中…" : "送出回答"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => void send("end")}
              >
                結束並產生總結
              </button>
            </div>
          </form>
        ) : (
          <Link href="/mockInterview" className="button secondary">
            返回面試紀錄
          </Link>
        )}
      </>
    );
  if (route[0] === "add")
    return (
      <>
        <span className="eyebrow">PREPARE YOUR INTERVIEW</span>
        <h1>開始一場模擬面試</h1>
        <p className="muted">設定職位與程度，面試官會根據回答持續追問。</p>
        <form
          className="form panel"
          onSubmit={(e) => {
            e.preventDefault();
            void action(async () => {
              const result = await api<Interview>(
                "/interviews",
                "POST",
                { position, experience, difficulty },
                user.csrf_token,
              );
              router.push("/mockInterview/chat/" + result.id);
            });
          }}
        >
          <label>
            <span>職位</span>
            <input
              required
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            />
          </label>
          <label>
            <span>工作經驗</span>
            <input
              value={experience}
              onChange={(e) => setExperience(e.target.value)}
            />
          </label>
          <label>
            <span>難度</span>
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
            >
              <option value="easy">入門</option>
              <option value="medium">中階</option>
              <option value="hard">進階</option>
            </select>
          </label>
          <button disabled={busy}>建立面試</button>
        </form>
      </>
    );
  return (
    <>
      <div className="section-title">
        <div>
          <span className="eyebrow">INTERVIEW PRACTICE</span>
          <h1>我的模擬面試</h1>
        </div>
        <Link href="/mockInterview/add" className="button">
          ＋ 新面試
        </Link>
      </div>
      <div className="panel">
        {items?.items.map((i) => (
          <div key={i.id} className="list-item">
            <Link href={"/mockInterview/chat/" + i.id}>
              <h3>{i.position}</h3>
              <span className="muted">
                {i.experience} · {i.status}
              </span>
            </Link>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await api(
                    "/interviews/" + i.id,
                    "DELETE",
                    undefined,
                    user.csrf_token,
                  );
                  await load(page);
                })
              }
            >
              刪除
            </button>
          </div>
        ))}
        {items?.total === 0 && (
          <p className="empty">還沒有面試紀錄，建立第一場面試吧。</p>
        )}
      </div>
      {items && (
        <Pagination
          page={page}
          total={items.total}
          onPage={(p) => void load(p)}
        />
      )}
    </>
  );
}

function Admin({
  route,
  user,
  action,
  busy,
  report,
}: {
  route: string[];
  user: User;
  action: Action;
  busy: boolean;
  report: (s: string) => void;
}) {
  const section = route[0] || "question";
  const [data, setData] = useState<Page<Json>>();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [edit, setEdit] = useState<Json | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [bankId, setBankId] = useState("");
  const [direction, setDirection] = useState("Python 後端開發");
  const [count, setCount] = useState(3);
  const [job, setJob] = useState<Job>();
  const [policy, setPolicy] = useState("rate");
  const [version, setVersion] = useState(0);
  const [policyText, setPolicyText] = useState("");
  const endpoint =
    section === "user"
      ? "/admin/users"
      : section === "questionBank"
        ? "/admin/banks"
        : section === "interviews"
          ? "/admin/interviews"
          : "/admin/questions";
  const base =
    section === "user"
      ? "/admin/users"
      : section === "questionBank"
        ? "/banks"
        : section === "interviews"
          ? "/interviews"
          : "/questions";
  const load = (p = page) =>
    action(async () => {
      setData(
        await api<Page<Json>>(
          endpoint +
            "?page=" +
            p +
            (section !== "interviews" ? "&q=" + encodeURIComponent(q) : ""),
        ),
      );
      setPage(p);
      setSelected([]);
    });
  useEffect(() => {
    setEdit(null);
    setForm({});
    setJob(undefined);
    if (section !== "policies" && route[1] !== "ai") void load(1);
  }, [section, route[1]]);
  useEffect(() => {
    if (section === "policies")
      void action(async () => {
        const p = await api<{ version: number; value: Json }>(
          "/admin/policies/" + policy,
        );
        setVersion(p.version);
        setPolicyText(JSON.stringify(p.value, null, 2));
      });
  }, [section, policy]);
  useEffect(() => {
    if (!job || !["pending", "running"].includes(job.state)) return;
    const timer = setInterval(() => {
      void api<Job>("/admin/question-generation-jobs/" + job.id)
        .then(setJob)
        .catch(() => {});
    }, 1500);
    return () => clearInterval(timer);
  }, [job?.id, job?.state]);
  if (section === "question" && route[1] === "ai")
    return (
      <>
        <span className="eyebrow">AI QUESTION STUDIO</span>
        <h1>AI 出題工作室</h1>
        <p className="muted">設定方向與數量，生成後逐題審核再公開。</p>
        <form
          className="panel form"
          onSubmit={(e) => {
            e.preventDefault();
            void action(async () =>
              setJob(
                await api<Job>(
                  "/admin/question-generation-jobs",
                  "POST",
                  { direction, count, request_id: crypto.randomUUID() },
                  user.csrf_token,
                ),
              ),
            );
          }}
        >
          <label>
            <span>出題方向</span>
            <input
              required
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            />
          </label>
          <label>
            <span>題目數量</span>
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </label>
          <button disabled={busy}>產生題目</button>
        </form>
        {job && (
          <div className="panel">
            <h2>
              工作 #{job.id} · {job.state}
            </h2>
            {job.error && (
              <p className="error">生成失敗，沒有寫入部分題目。可以重試。</p>
            )}
            {job.state === "failed" && (
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () =>
                    setJob(
                      await api<Job>(
                        "/admin/question-generation-jobs",
                        "POST",
                        { ...job.input, request_id: job.request_id },
                        user.csrf_token,
                      ),
                    ),
                  )
                }
              >
                重試原工作
              </button>
            )}
            {job.result.map((id) => (
              <p key={id}>題目 #{id} 已生成，待審核。</p>
            ))}
            {job.state === "completed" && (
              <Link className="button secondary" href="/admin/question">
                前往題目管理審核
              </Link>
            )}
          </div>
        )}
      </>
    );
  if (section === "policies")
    return (
      <>
        <span className="eyebrow">SERVICE OPERATIONS</span>
        <h1>服務政策</h1>
        <div className="panel">
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              void action(async () => {
                const p = await api<{ version: number; value: Json }>(
                  "/admin/policies/" + policy,
                  "PATCH",
                  { version, value: JSON.parse(policyText) },
                  user.csrf_token,
                );
                setVersion(p.version);
                report("政策已更新，所有 API instance 會重新載入");
              });
            }}
          >
            <label>
              <span>政策</span>
              <select
                value={policy}
                onChange={(e) => setPolicy(e.target.value)}
              >
                {["rate", "crawl", "ip", "breaker", "cache"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
            <label>
              <span>政策值 · 版本 {version}</span>
              <textarea
                rows={12}
                value={policyText}
                onChange={(e) => setPolicyText(e.target.value)}
              />
            </label>
            <button disabled={busy}>保存政策</button>
          </form>
        </div>
        <div className="actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                const r = await api<Json>(
                  "/admin/search/rebuild",
                  "POST",
                  {},
                  user.csrf_token,
                );
                report("索引重建完成，文件數：" + r.documents);
              })
            }
          >
            重建搜尋索引
          </button>
          <button
            className="secondary"
            onClick={() =>
              void action(async () =>
                report(JSON.stringify(await api<Json>("/admin/worker/status"))),
              )
            }
          >
            查看同步狀態
          </button>
          <button
            className="secondary"
            onClick={() =>
              void action(async () =>
                report(JSON.stringify(await api<Json>("/admin/cache/stats"))),
              )
            }
          >
            快取統計
          </button>
        </div>
      </>
    );
  const isBank = section === "questionBank",
    isUser = section === "user",
    isInterview = section === "interviews";
  const fields = isUser
    ? edit?.id
      ? [
          ["name", "姓名"],
          ["avatar_url", "頭像 URL"],
          ["bio", "簡介"],
          ["role", "角色"],
        ]
      : [
          ["account", "帳號"],
          ["password", "密碼"],
          ["confirmation", "確認密碼"],
          ["name", "姓名"],
          ["avatar_url", "頭像 URL"],
          ["bio", "簡介"],
          ["role", "角色"],
        ]
    : isBank
      ? [
          ["title", "題庫名稱"],
          ["description", "介紹"],
          ["picture_url", "圖片 URL"],
        ]
      : [
          ["title", "題目標題"],
          ["content", "題目內容"],
          ["answer", "題解"],
          ["tags", "標籤（逗號分隔）"],
          ["review_status", "審核狀態"],
        ];
  function open(row: Json | null) {
    setEdit(row || {});
    setForm(
      Object.fromEntries(
        fields.map(([k]) => [
          k,
          k === "tags"
            ? ((row?.tags as string[]) || []).join(",")
            : String(
                row?.[k] ??
                  (k === "role"
                    ? "user"
                    : k === "review_status"
                      ? "approved"
                      : ""),
              ),
        ]),
      ),
    );
  }
  function save(e: FormEvent) {
    e.preventDefault();
    void action(async () => {
      const body: Json = Object.fromEntries(
        fields.map(([key]) => [key, form[key] || ""]),
      );
      if (!isUser && !isBank)
        body.tags = (form.tags || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      if (edit?.version) body.version = edit.version;
      await api(
        base + (edit?.id ? "/" + edit.id : ""),
        edit?.id ? "PATCH" : "POST",
        body,
        user.csrf_token,
      );
      setEdit(null);
      await load(page);
      report("資料已保存");
    });
  }
  return (
    <>
      <div className="section-title">
        <div>
          <span className="eyebrow">ADMIN WORKSPACE</span>
          <h1>
            {isUser
              ? "使用者管理"
              : isBank
                ? "題庫管理"
                : isInterview
                  ? "面試紀錄"
                  : "題目管理"}
          </h1>
        </div>
        {!isInterview && <button onClick={() => open(null)}>＋ 新增</button>}
      </div>
      {edit && (
        <form className="panel form" onSubmit={save}>
          <h2>{edit.id ? "編輯 #" + edit.id : "新增資料"}</h2>
          {fields.map(([key, label]) => (
            <label key={key}>
              <span>{label}</span>
              {["content", "answer", "description"].includes(key) ? (
                <textarea
                  value={form[key] || ""}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                />
              ) : ["role", "review_status"].includes(key) ? (
                <select
                  value={form[key] || ""}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                >
                  {(key === "role" ? roleOptions : reviewOptions).map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              ) : (
                <input
                  required={[
                    "title",
                    "account",
                    "password",
                    "confirmation",
                    "name",
                  ].includes(key)}
                  type={
                    ["password", "confirmation"].includes(key)
                      ? "password"
                      : "text"
                  }
                  value={form[key] || ""}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                />
              )}
            </label>
          ))}
          <div className="actions">
            <button disabled={busy}>保存</button>
            <button
              type="button"
              className="secondary"
              onClick={() => setEdit(null)}
            >
              取消
            </button>
          </div>
        </form>
      )}
      {!isInterview && (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            void load(1);
          }}
        >
          <input
            aria-label="管理搜尋"
            placeholder={isUser ? "搜尋帳號" : "搜尋標題"}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button>搜尋</button>
        </form>
      )}
      {!isBank && !isUser && !isInterview && (
        <div className="toolbar">
          <input
            aria-label="批次題庫 ID"
            placeholder="題庫 ID"
            value={bankId}
            onChange={(e) => setBankId(e.target.value)}
          />
          {[
            ["POST", "加入題庫"],
            ["DELETE", "移出題庫"],
          ].map(([method, label]) => (
            <button
              key={method}
              className="secondary"
              disabled={busy || !selected.length || !bankId}
              onClick={() =>
                void action(async () => {
                  report(
                    JSON.stringify(
                      await api<Json>(
                        "/banks/" + bankId + "/questions/batch",
                        method,
                        { ids: selected },
                        user.csrf_token,
                      ),
                    ),
                  );
                })
              }
            >
              {label}
            </button>
          ))}
          <button
            className="danger"
            disabled={busy || !selected.length}
            onClick={() =>
              void action(async () => {
                await api(
                  "/questions/batch-delete",
                  "POST",
                  { ids: selected },
                  user.csrf_token,
                );
                await load(page);
                report("選取的題目已刪除");
              })
            }
          >
            批次刪除 ({selected.length})
          </button>
        </div>
      )}
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              {!isBank && !isUser && !isInterview && <th>選取</th>}
              <th>ID</th>
              <th>{isUser ? "姓名 / 帳號" : isInterview ? "職位" : "標題"}</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((row) => (
              <tr key={String(row.id)}>
                {!isBank && !isUser && !isInterview && (
                  <td>
                    <input
                      className="checkbox"
                      type="checkbox"
                      aria-label={"選取題目 " + row.id}
                      checked={selected.includes(String(row.id))}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...selected, String(row.id)]
                            : selected.filter((id) => id !== row.id),
                        )
                      }
                    />
                  </td>
                )}
                <td>{String(row.id)}</td>
                <td>
                  {String(row.title || row.name || row.position)}
                  {isUser && <p className="muted">{String(row.account)}</p>}
                </td>
                <td>
                  {String(
                    row.role || row.review_status || row.status || "公開",
                  )}
                </td>
                <td>
                  <div className="actions">
                    {!isInterview && (
                      <button className="secondary" onClick={() => open(row)}>
                        編輯
                      </button>
                    )}
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await api(
                            base + "/" + row.id,
                            "DELETE",
                            undefined,
                            user.csrf_token,
                          );
                          await load(page);
                        })
                      }
                    >
                      刪除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.total === 0 && <p className="empty">目前沒有資料</p>}
      </div>
      {data && (
        <Pagination
          page={page}
          total={data.total}
          onPage={(p) => void load(p)}
        />
      )}
    </>
  );
}

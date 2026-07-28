import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Bell,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Cloud,
  Copy,
  Download,
  Folder,
  Info,
  Link2,
  LoaderCircle,
  Pause,
  Play,
  RefreshCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Upload,
  Wifi,
  X,
} from "lucide-react";
import "./styles.css";

type View = "sync" | "notifications" | "about";
type FolderItem = { id: string; name: string; path: string };
type FolderPage = { items: FolderItem[]; nextCursor?: string | null };
type GraphState = { state: string; message?: string; verified?: boolean };
type SyncAuth = { state?: string; verificationUri?: string; userCode?: string; message?: string };
type Progress = {
  downloadsCompleted?: number; uploadsCompleted?: number; activeDownload?: string; activeUpload?: string;
  downloadPercent?: number; uploadPercent?: number; downloadSpeed?: number; uploadSpeed?: number;
  downloadBytes?: number; uploadBytes?: number; scanItems?: number; plannedDownloads?: number; activity?: string;
};
type SyncStatus = {
  mode: string; running: boolean; authorization?: SyncAuth; progress?: Progress;
  operation?: { phase?: string; message?: string; error?: string; startedAt?: string; finishedAt?: string };
};
type Health = { ok: boolean; version?: string; sync: SyncStatus; graph: GraphState; account?: { displayName?: string; userPrincipalName?: string }; scopeConfigured?: boolean };
type NotificationSettings = { enabled: boolean; configured: boolean; endpointPreview?: string; endpointHost?: string; events?: { syncError?: boolean; graphDisconnected?: boolean } };

const modeName: Record<string, string> = { monitor: "持续同步中", once: "单次同步中", stopped: "已停止", reauth: "等待同步授权", resync_pending: "准备重同步", resync: "正在重同步" };
const phaseName: Record<string, string> = { queued: "任务已排队", dry_run: "安全检查中", resync: "正在重同步", succeeded: "重同步已完成", failed: "重同步失败", cancelled: "重同步已取消" };

async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({ detail: `服务返回无效响应 (${response.status})` }));
  if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`);
  return data as T;
}

function bytes(value = 0) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** index;
  return `${amount >= 100 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function toneForLog(line: string) {
  if (/ERROR|failed|拒绝|异常|File name too long/i.test(line)) return "error";
  if (/WARNING|interrupted|Retrying|重试/i.test(line)) return "warning";
  if (/Downloading|Fetching|Processing|Scanning/i.test(line)) return "download";
  if (/Uploading/i.test(line)) return "upload";
  if (/done|complete|成功|已完成/i.test(line)) return "success";
  return "plain";
}

async function copy(value: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // HTTP management pages require the legacy user-gesture fallback below.
    }
  }

  const field = document.createElement("textarea");
  field.value = value;
  field.setAttribute("readonly", "");
  field.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
  document.body.appendChild(field);
  field.select();
  field.setSelectionRange(0, value.length);
  const copied = document.execCommand("copy");
  field.remove();
  return copied;
}

function App() {
  const [view, setView] = useState<View>((location.hash.slice(1) as View) || "sync");
  const [health, setHealth] = useState<Health | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [folders, setFolders] = useState<Record<string, FolderItem[]>>({});
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [savedPaths, setSavedPaths] = useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [showSyncAuth, setShowSyncAuth] = useState(false);
  const [showGraphAuth, setShowGraphAuth] = useState(false);
  const [deviceCode, setDeviceCode] = useState<{ code: string; url: string; message: string } | null>(null);
  const [graphPolling, setGraphPolling] = useState(false);
  const [notification, setNotification] = useState<NotificationSettings | null>(null);
  const [webhook, setWebhook] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [nextHealth, nextLogs] = await Promise.all([api<Health>("/api/health"), api<{ lines: string[] }>("/api/logs?limit=160")]);
      setHealth(nextHealth); setLogs(nextLogs.lines); setNotice("");
    } catch (error) { setNotice(error instanceof Error ? error.message : "管理服务暂时不可用"); }
  }, []);

  const loadSelection = useCallback(async () => {
    try {
      const data = await api<{ folders: string[] }>("/api/selection");
      const saved = new Set(data.folders); setSavedPaths(saved); setSelectedPaths(new Set(saved));
    } catch (error) { setNotice(error instanceof Error ? error.message : "读取同步范围失败"); }
  }, []);

  useEffect(() => { void refresh(); void loadSelection(); }, [refresh, loadSelection]);
  useEffect(() => {
    const interval = window.setInterval(() => void refresh(), health?.sync.running ? 3000 : 6000);
    return () => window.clearInterval(interval);
  }, [health?.sync.running, refresh]);
  useEffect(() => { location.hash = view; }, [view]);

  const fetchChildren = useCallback(async (parentId: string) => {
    if (folders[parentId]) return folders[parentId];
    setBusy(`folder:${parentId}`);
    try {
      const collected: FolderItem[] = []; let cursor: string | null | undefined;
      do {
        const parameters = new URLSearchParams({ parent_id: parentId }); if (cursor) parameters.set("cursor", cursor);
        const page = await api<FolderPage>(`/api/folders?${parameters}`); collected.push(...page.items); cursor = page.nextCursor;
      } while (cursor);
      setFolders(current => ({ ...current, [parentId]: collected })); return collected;
    } finally { setBusy(""); }
  }, [folders]);

  const resolveSavedPaths = useCallback(async (paths: Set<string>) => {
    const ids = new Set<string>();
    for (const value of paths) {
      let parent = "root"; let path = "";
      for (const segment of value.split("/")) {
        path = path ? `${path}/${segment}` : segment;
        const items = await fetchChildren(parent); const match = items.find(item => item.path === path);
        if (!match) break; parent = match.id;
      }
      if (parent !== "root") ids.add(parent);
    }
    setSelectedIds(ids);
  }, [fetchChildren]);

  const loadRoot = async () => {
    try {
      await fetchChildren("root"); await resolveSavedPaths(savedPaths); setNotice("");
    } catch (error) { setNotice(error instanceof Error ? error.message : "加载目录失败"); }
  };

  const toggleFolder = async (folder: FolderItem) => {
    if (openFolders.has(folder.id)) { setOpenFolders(current => { const next = new Set(current); next.delete(folder.id); return next; }); return; }
    try { await fetchChildren(folder.id); setOpenFolders(current => new Set(current).add(folder.id)); }
    catch (error) { setNotice(error instanceof Error ? error.message : "加载子目录失败"); }
  };

  const chooseFolder = (folder: FolderItem, checked: boolean) => {
    setSelectedPaths(current => {
      const next = new Set(current);
      if (checked) next.add(folder.path); else for (const path of [...next]) if (path === folder.path || path.startsWith(`${folder.path}/`)) next.delete(path);
      return next;
    });
    setSelectedIds(current => { const next = new Set(current); if (checked) next.add(folder.id); else next.delete(folder.id); return next; });
  };

  const saveScope = async () => {
    if (!selectedIds.size) { setNotice("至少选择一个文件夹。"); return; }
    setBusy("scope");
    try {
      const preview = await api<{ folders: string[]; current: string[] }>("/api/selection/preview", { method: "POST", body: JSON.stringify({ folder_ids: [...selectedIds] }) });
      const add = preview.folders.filter(path => !preview.current.includes(path)); const remove = preview.current.filter(path => !preview.folders.includes(path));
      if (!window.confirm(`确认保存同步范围？\n新增 ${add.length} 个，移除 ${remove.length} 个。保存后需执行受控重同步。`)) return;
      const result = await api<{ folders: string[] }>("/api/selection/apply", { method: "POST", body: JSON.stringify({ folder_ids: [...selectedIds], confirm: true }) });
      const saved = new Set(result.folders); setSavedPaths(saved); setSelectedPaths(saved); setNotice("同步范围已保存，请执行受控重同步。");
    } catch (error) { setNotice(error instanceof Error ? error.message : "保存同步范围失败"); }
    finally { setBusy(""); }
  };

  const command = async (name: "start" | "once" | "stop" | "reauth" | "resync") => {
    if (name === "resync" && !window.confirm("将先执行 dry-run，检查通过后重同步当前范围。继续吗？")) return;
    if (name === "reauth") setShowSyncAuth(true);
    setBusy(name);
    try {
      await api(`/api/sync/${name}`, { method: "POST", body: name === "resync" ? JSON.stringify({ confirm: true }) : undefined });
      await refresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(""); }
  };

  const beginGraphAuth = async () => {
    setBusy("graph"); setShowGraphAuth(true);
    try {
      const result = await api<{ user_code: string; verification_uri: string; message?: string }>("/api/graph/auth/device-code", { method: "POST" });
      setDeviceCode({ code: result.user_code, url: result.verification_uri, message: result.message || "请打开 Microsoft 登录页并输入代码。" });
    } catch (error) { setNotice(error instanceof Error ? error.message : "无法发起 Graph 授权"); }
    finally { setBusy(""); }
  };

  const pollGraph = useCallback(async () => {
    if (!deviceCode || graphPolling) return;
    setGraphPolling(true);
    try { await api("/api/graph/auth/poll", { method: "POST" }); setDeviceCode(null); setShowGraphAuth(false); await refresh(); }
    catch (error) { const message = error instanceof Error ? error.message : "授权状态未知"; if (!/pending|等待/i.test(message)) setNotice(message); }
    finally { setGraphPolling(false); }
  }, [deviceCode, graphPolling, refresh]);
  useEffect(() => { if (!deviceCode) return; const timer = window.setInterval(() => void pollGraph(), 5000); return () => window.clearInterval(timer); }, [deviceCode, pollGraph]);

  const loadNotifications = async () => {
    try { const result = await api<NotificationSettings>("/api/notifications"); setNotification(result); }
    catch (error) { setNotice(error instanceof Error ? error.message : "读取通知设置失败"); }
  };
  useEffect(() => { if (view === "notifications") void loadNotifications(); }, [view]);
  const saveNotifications = async () => {
    if (!notification) return; setBusy("notify");
    try {
      const result = await api<NotificationSettings>("/api/notifications", { method: "PUT", body: JSON.stringify({ enabled: notification.enabled, webhook_url: webhook, events: notification.events || {} }) });
      setNotification(result); setWebhook(""); setNotice("通知设置已保存。");
    } catch (error) { setNotice(error instanceof Error ? error.message : "保存通知设置失败"); }
    finally { setBusy(""); }
  };

  const graph = health?.graph; const sync = health?.sync; const progress = sync?.progress || {};
  const direction = progress.activeDownload ? "download" : progress.activeUpload ? "upload" : "idle";
  const currentPath = progress.activeDownload || progress.activeUpload || progress.activity || "等待同步任务";
  const percent = direction === "download" ? progress.downloadPercent : direction === "upload" ? progress.uploadPercent : undefined;
  const scopeChanged = useMemo(() => [...selectedPaths].sort().join("\n") !== [...savedPaths].sort().join("\n"), [selectedPaths, savedPaths]);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><img src="/static/onesync-logo.png" alt="OneSync" /><div><strong>OneSync</strong><span>UNRAID · ONEDRIVE</span></div></div>
      <nav className="nav-list" aria-label="主导航">
        <Nav icon={<Cloud />} label="同步" active={view === "sync"} onClick={() => setView("sync")} />
        <Nav icon={<Bell />} label="通知" active={view === "notifications"} onClick={() => setView("notifications")} />
        <Nav icon={<Info />} label="关于" active={view === "about"} onClick={() => setView("about")} />
      </nav>
      <div className="sidebar-status"><span className={`dot ${sync?.running ? "online" : ""}`} />{sync?.running ? "引擎运行中" : "引擎已停止"}</div>
    </aside>
    <main className="content">
      <header className="page-header"><div><p className="eyebrow">{view === "sync" ? "SYNCHRONIZATION" : view.toUpperCase()}</p><h1>{view === "sync" ? "同步控制台" : view === "notifications" ? "通知设置" : "关于 OneSync"}</h1></div><div className="header-meta"><span className={`status-pill ${graph?.verified ? "good" : ""}`}><Wifi size={14} />{graph?.verified ? "Graph 已连接" : graph?.state === "pending" ? "正在授权" : "Graph 待验证"}</span><span className="account">{health?.account?.displayName || health?.account?.userPrincipalName || "5dldn8.onmicrosoft.com"}</span></div></header>
      {notice && <div className="notice"><CircleAlert size={18} /><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice("")}><X size={16} /></button></div>}
      {view === "sync" && <>
        <section className="hero-grid">
          <div className="surface status-surface">
            <div className="surface-head"><div><span className="label">同步引擎</span><h2>{modeName[sync?.mode || ""] || "正在读取状态"}</h2></div><span className={`engine-orb ${sync?.running ? "active" : ""}`}><Activity size={21} /></span></div>
            <p className="muted">{sync?.running ? "本地与云端改动将按当前范围同步" : "选择范围后启动持续同步或执行一次同步"}</p>
            <div className="operation-state"><span className="operation-label">{phaseName[sync?.operation?.phase || ""] || "同步状态正常"}</span><span>{sync?.operation?.error || sync?.operation?.message || "引擎等待下一项任务"}</span></div>
          </div>
          <div className="surface transfer-surface">
            <div className="surface-head compact"><div><span className="label">当前传输</span><h2>{direction === "download" ? "云端 → 本地" : direction === "upload" ? "本地 → 云端" : "准备就绪"}</h2></div><span className="transfer-icon">{direction === "upload" ? <Upload size={19} /> : <Download size={19} />}</span></div>
            <p className="file-path" title={currentPath}>{currentPath}</p>
            <div className="progress-line"><div className={`progress-track ${direction}`}><span style={{ width: `${percent ?? 0}%` }} /></div><strong>{percent === undefined ? "--" : `${percent}%`}</strong></div>
            <div className="metrics"><span>下载 {bytes(progress.downloadSpeed)}/s</span><span>上传 {bytes(progress.uploadSpeed)}/s</span><span>完成 {Number(progress.downloadsCompleted || 0) + Number(progress.uploadsCompleted || 0)} 个</span></div>
            <p className="muted mini">{progress.scanItems ? `已校验 ${progress.scanItems.toLocaleString("zh-CN")} 个云端条目` : progress.plannedDownloads != null ? `待下载 ${progress.plannedDownloads} 个文件` : "传输开始后显示速度与进度"}</p>
          </div>
        </section>
        <section className="surface control-surface"><div className="surface-head compact"><div><span className="label">操作</span><h2>同步控制</h2></div><span className="muted mini">范围：{savedPaths.size ? `已选择 ${savedPaths.size} 个文件夹` : "尚未选择"}</span></div><div className="control-row">
          <ActionButton icon={<Play size={17} />} label="持续同步" primary disabled={Boolean(busy) || Boolean(sync?.operation?.phase && !["failed", "succeeded", "cancelled"].includes(sync.operation.phase))} onClick={() => void command("start")} />
          <ActionButton icon={<RefreshCcw size={17} />} label="同步一次" disabled={Boolean(busy) || !savedPaths.size} onClick={() => void command("once")} />
          <ActionButton icon={<Pause size={17} />} label="停止" danger disabled={!sync?.running && sync?.operation?.phase !== "resync"} onClick={() => void command("stop")} />
          <ActionButton icon={<Link2 size={17} />} label="同步授权" disabled={Boolean(busy)} onClick={() => void command("reauth")} />
          <ActionButton icon={<SlidersHorizontal size={17} />} label="受控重同步" disabled={Boolean(busy) || !savedPaths.size} onClick={() => void command("resync")} />
        </div></section>
        <section className="surface scope-surface"><div className="surface-head"><div><span className="label">同步范围</span><h2>OneDrive 文件夹</h2></div><div className="scope-actions"><span className={scopeChanged ? "changed" : "muted mini"}>{scopeChanged ? "有未保存更改" : `已选 ${selectedPaths.size} 个`}</span><button className="quiet-button" disabled={busy === "graph"} onClick={() => void beginGraphAuth()}><Link2 size={16} />{graph?.state === "authorized" ? "重新授权" : "连接 Graph"}</button><button className="quiet-button" disabled={busy === "folder:root"} onClick={() => void loadRoot()}>{busy.startsWith("folder:") ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />}刷新目录</button><button className="primary-button" disabled={busy === "scope" || !scopeChanged || !selectedIds.size} onClick={() => void saveScope()}><Save size={16} />保存范围</button></div></div>
          <div className="tree-wrap">{folders.root ? <FolderTree items={folders.root} folders={folders} open={openFolders} selected={selectedPaths} onToggle={toggleFolder} onChoose={chooseFolder} busy={busy} /> : <button className="empty-tree" onClick={() => void loadRoot()}><Folder size={23} />加载 OneDrive 文件夹</button>}</div>
        </section>
        <section className="surface logs-surface"><div className="surface-head compact"><div><span className="label">诊断</span><h2>同步日志</h2></div><span className="muted mini">最近 {logs.length} 行</span></div><pre className="logs">{logs.map((line, index) => <span className={`log ${toneForLog(line)}`} key={`${index}-${line.slice(0, 24)}`}>{line}{"\n"}</span>)}</pre></section>
      </>}
      {view === "notifications" && <section className="surface settings-surface"><div className="surface-head"><div><span className="label">WEBHOOK</span><h2>通知规则</h2></div><Bell className="decorative" /></div><div className="setting-list"><ToggleRow label="启用 Webhook 通知" detail="同步错误、云端对象缺失或 Graph 断线时发送通知" checked={Boolean(notification?.enabled)} onChange={checked => setNotification(current => current ? { ...current, enabled: checked } : current)} /><label className="field"><span>Webhook 地址</span><input value={webhook} onChange={event => setWebhook(event.target.value)} placeholder={notification?.endpointPreview || "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…"} /><small>留空保存会保留当前已配置地址。</small></label><ToggleRow label="同步错误" detail="下载、上传、远端缺失与同步引擎失败" checked={notification?.events?.syncError !== false} onChange={checked => setNotification(current => current ? { ...current, events: { ...current.events, syncError: checked } } : current)} /><ToggleRow label="Graph 断线" detail="Microsoft Graph 授权或连通性异常" checked={notification?.events?.graphDisconnected !== false} onChange={checked => setNotification(current => current ? { ...current, events: { ...current.events, graphDisconnected: checked } } : current)} /></div><div className="form-actions"><button className="primary-button" disabled={busy === "notify" || !notification} onClick={() => void saveNotifications()}><Save size={16} />保存通知设置</button><button className="quiet-button" disabled={busy === "test-notify" || !notification} onClick={() => void (async () => { setBusy("test-notify"); try { await api("/api/notifications/test", { method: "POST" }); setNotice("测试通知已发送。"); } catch (error) { setNotice(error instanceof Error ? error.message : "发送失败"); } finally { setBusy(""); } })()}><Bell size={16} />发送测试通知</button></div></section>}
      {view === "about" && <section className="about-grid"><div className="surface about-main"><span className="label">ONESYNC FOR UNRAID</span><h2>让 OneDrive 同步，留在自己的存储里。</h2><p className="muted">OneSync 使用官方 OneDrive 同步引擎，把选中的目录同步为 Unraid 上真实可用的本地文件。</p><div className="project-meta"><Meta label="版本" value={health?.version || "读取中"} /><Meta label="同步引擎" value="driveone/onedrive" /><Meta label="源码" value="GitHub / Wning-ady/OneSync" /></div></div><div className="surface graph-card"><Cloud size={24} /><h3>Microsoft Graph</h3><p>{graph?.verified ? "文件夹浏览权限已连接" : graph?.message || "用于加载 OneDrive 文件夹树"}</p><button className="primary-button" disabled={busy === "graph"} onClick={() => void beginGraphAuth()}>{graph?.state === "authorized" ? "重新授权" : "连接 Graph"}</button></div><div className="surface support-card"><div><span className="label">最后的最后</span><h3>请我喝一瓶快乐水</h3><p>你的支持是持续维护和更新项目的最大动力。</p></div><div className="qr-pair"><img className="wechat" src="/static/donate-wechat-qr.png" alt="微信支付" /><img className="alipay" src="/static/donate-alipay-qr.png" alt="支付宝" /></div></div></section>}
    </main>
    {showSyncAuth && <DeviceDialog title="Microsoft 同步授权" auth={sync?.authorization} onClose={() => setShowSyncAuth(false)} />}
    {showGraphAuth && <DeviceDialog title="Microsoft Graph 授权" auth={deviceCode ? { userCode: deviceCode.code, verificationUri: deviceCode.url, message: deviceCode.message } : { message: "正在获取设备代码…" }} onClose={() => setShowGraphAuth(false)} />}
  </div>;
}

function Nav({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) { return <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>{icon}<span>{label}</span></button>; }
function ActionButton({ icon, label, primary, danger, disabled, onClick }: { icon: React.ReactNode; label: string; primary?: boolean; danger?: boolean; disabled?: boolean; onClick: () => void }) { return <button className={`action-button ${primary ? "primary" : ""} ${danger ? "danger" : ""}`} disabled={disabled} onClick={onClick}>{icon}{label}</button>; }
function Meta({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function ToggleRow({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (checked: boolean) => void }) { return <label className="toggle-row"><div><strong>{label}</strong><span>{detail}</span></div><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} /><i aria-hidden="true" /></label>; }
function DeviceDialog({ title, auth, onClose }: { title: string; auth?: SyncAuth; onClose: () => void }) {
  const code = auth?.userCode || "";
  const [copyMessage, setCopyMessage] = useState("");
  const copyCode = async () => {
    const copied = code && await copy(code);
    setCopyMessage(copied ? "授权码已复制" : "复制失败，请手动选择代码");
  };
  return <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label={title}><button className="modal-close" onClick={onClose}><X size={18} /></button><span className="label">MICROSOFT DEVICE CODE</span><h2>{title}</h2><p>{auth?.message || "请完成 Microsoft 授权。"}</p><button className="device-code" disabled={!code} aria-label="复制授权码" onClick={() => void copyCode()}>{code || "等待授权码"}<Copy size={18} /></button><div className="form-actions"><a className={`primary-button ${auth?.verificationUri ? "" : "disabled"}`} href={auth?.verificationUri} target="_blank" rel="noreferrer">打开登录页</a><button className="quiet-button" disabled={!code} onClick={() => void copyCode()}>{copyMessage || "复制代码"}</button></div>{copyMessage && <p className="copy-status" role="status">{copyMessage}</p>}</section></div>;
}
function FolderTree({ items, folders, open, selected, onToggle, onChoose, busy }: { items: FolderItem[]; folders: Record<string, FolderItem[]>; open: Set<string>; selected: Set<string>; onToggle: (item: FolderItem) => void; onChoose: (item: FolderItem, checked: boolean) => void; busy: string }) { return <ul className="folder-tree">{items.map(item => <li key={item.id}><div className="folder-row"><button className="chevron" onClick={() => void onToggle(item)} aria-label={`展开 ${item.name}`}>{busy === `folder:${item.id}` ? <LoaderCircle className="spin" size={15} /> : open.has(item.id) ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</button><input id={`folder-${item.id}`} type="checkbox" checked={selected.has(item.path)} onChange={event => onChoose(item, event.target.checked)} /><label htmlFor={`folder-${item.id}`}><Folder size={16} /><span>{item.name}</span><small>{item.path}</small></label></div>{open.has(item.id) && folders[item.id] && <FolderTree items={folders[item.id]} folders={folders} open={open} selected={selected} onToggle={onToggle} onChoose={onChoose} busy={busy} />}</li>)}</ul>; }

createRoot(document.getElementById("root")!).render(<App />);

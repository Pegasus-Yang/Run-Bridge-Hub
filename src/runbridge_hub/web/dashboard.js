"use strict";

// 口令不写入浏览器存储；所有节点内容按文本渲染。
const $ = (id) => document.getElementById(id);
const stateNames = {ONLINE: "在线", PREPARING: "准备中", OFFLINE: "离线"};
const backendNames = {playwright: "Playwright", "chrome-cdp": "Chrome CDP"};
const readinessNames = {READY: "已就绪", NEEDS_PROBE: "待探测", NEEDS_AUTHORIZATION: "待授权", UNAVAILABLE: "不可用"};
const coverageNames = {SUPPORTED: "已支持", REQUIRES_VERIFICATION: "待验证", NOT_IMPLEMENTED: "未实现"};
const leaseNames = {UNCLAIMED: "未领取", HELD: "已领取", RELEASING: "回收中", QUARANTINED: "待核查"};
let token = "";
let snapshot = null;
let receivedAt = 0;
let filter = "ALL";
let search = "";
let selectedId = null;
let timer = null;
let pending = null;
let generation = 0;

function element(tag, className = "", text = null) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== null) item.textContent = String(text);
  return item;
}

function icon(name) {
  const item = element("span", `icon icon-${name}`);
  item.setAttribute("aria-hidden", "true");
  return item;
}

function relativeTime(date) {
  if (!date || !snapshot) return "—";
  const now = Date.parse(snapshot.snapshot_at) + performance.now() - receivedAt;
  const seconds = Math.max(0, Math.floor((now - Date.parse(date)) / 1000));
  if (seconds < 1) return "刚刚";
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function formatTime(date) {
  return date ? new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false}).format(new Date(date)) : "尚未上报";
}

function hostLabel(node) {
  const host = node.capabilities?.host || {};
  return [host.platform, host.machine].filter(Boolean).join(" · ");
}

function occupancyLabel(node) {
  const counts = node.resources;
  if (node.connection_status !== "ONLINE") return "未知";
  if (!counts.total) return "无执行资源";
  if (counts.busy === counts.total) return "已占用";
  if (counts.busy) return "部分占用";
  if (counts.unknown) return "占用未知";
  if (counts.unavailable) return counts.available ? "部分未就绪" : "未就绪";
  return "空闲";
}

function supportedCapabilities(node) {
  const values = new Set();
  for (const backend of node.capabilities?.backends || []) {
    if (backend.coverage_status !== "SUPPORTED" || backend.name === "runbridge-node") continue;
    values.add(backendNames[backend.name] || backend.name);
    if (backend.declared_protocols.includes("runbridge-visual-v1")) values.add("画面流");
  }
  return [...values];
}

function connectionState(node) {
  const label = element("span", `state ${node.connection_status}`);
  label.append(element("span", "dot"), document.createTextNode(stateNames[node.connection_status]));
  return label;
}

function latencyText(node) {
  const latency = node.latency;
  if (node.connection_status === "OFFLINE") return "—";
  if (latency.status === "STALE" || (latency.status === "MEASURED" && latency.sample_age_ms + performance.now() - receivedAt >= 60000)) return "已过期";
  if (latency.status === "MEASURED") {
    const value = latency.rtt_ms;
    return `${value < 1 ? value.toFixed(2) : value.toFixed(1)} ms`;
  }
  return latency.status === "UNAVAILABLE" ? "未启用测量" : "待测量";
}

function resourceCell(node) {
  const group = element("div", "occupancy");
  const counts = node.resources;
  if (counts.total && node.connection_status === "ONLINE") {
    const meter = element("span", "resource-meter");
    meter.setAttribute("aria-hidden", "true");
    const segments = Math.min(counts.total, 8);
    for (let i = 0; i < segments; i++) {
      const index = i * counts.total / segments;
      meter.append(element("span", index < counts.busy ? "busy" : index >= counts.busy + counts.available ? "unavailable" : ""));
    }
    group.append(meter);
  }
  const text = element("div", "resource-label");
  const reliable = node.connection_status === "ONLINE" && counts.total > 0 && counts.unknown === 0;
  const label = reliable ? `${counts.busy} / ${counts.total} 已占用` : node.connection_status === "ONLINE" && !counts.total ? "无执行资源" : "未知";
  text.append(document.createTextNode(label));
  const note = node.connection_status === "OFFLINE" ? "历史快照" : node.connection_status === "PREPARING" ? "等待能力上报" : occupancyLabel(node);
  if (note !== label) text.append(element("div", `resource-note${counts.busy ? " busy" : ""}`, note));
  text.append(element("div", "resource-note", `Node 使用权：${leaseNames[node.lease?.state] || "未知"}`));
  group.append(text);
  return group;
}

function capabilityCell(node) {
  const group = element("div", "capabilities");
  if (node.connection_status === "PREPARING") return element("span", "muted", "等待上报");
  const values = supportedCapabilities(node);
  if (node.capabilities_stale && values.length) group.append(element("span", "chip", "历史"));
  for (const value of values.slice(0, 3)) group.append(element("span", "chip", value));
  if (values.length > 3) group.append(element("span", "chip", `+${values.length - 3}`));
  if (!values.length) group.append(element("span", "muted", node.capabilities ? "暂无已支持能力" : "尚未上报"));
  return group;
}

function renderRows() {
  if (!snapshot) return;
  const focusedNode = document.activeElement?.dataset.node;
  const matching = snapshot.nodes.filter((node) => {
    const host = node.capabilities?.host || {};
    return (filter === "ALL" || node.connection_status === filter) && [node.name, node.node_id, host.hostname, host.platform, host.machine].filter(Boolean).join(" ").toLocaleLowerCase().includes(search);
  }).sort((left, right) => {
    const rank = {ONLINE: 0, PREPARING: 1, OFFLINE: 2};
    return rank[left.connection_status] - rank[right.connection_status] || left.name.localeCompare(right.name, "zh-CN");
  });
  const rows = document.createDocumentFragment();
  for (const node of matching) {
    const row = element("tr", node.node_id === selectedId ? "selected" : "");
    const addCell = (label, content) => {
      const cell = element("td");
      cell.dataset.label = label;
      cell.append(content);
      row.append(cell);
    };
    const name = element("button", "node-open");
    name.type = "button";
    name.dataset.node = node.node_id;
    name.setAttribute("aria-label", `查看 ${node.name} 的节点详情`);
    const meta = element("div", "node-meta", [node.node_id, hostLabel(node)].filter(Boolean).join(" · "));
    meta.title = meta.textContent;
    name.append(element("div", "node-name", node.name), meta);
    name.addEventListener("click", () => openDetail(node.node_id));
    addCell("节点", name);
    addCell("连接状态", connectionState(node));
    addCell("资源占用", resourceCell(node));
    addCell("支持能力", capabilityCell(node));
    const latency = element("div", "latency");
    const number = element("span", node.latency.status === "MEASURED" ? "latency-number" : "muted", latencyText(node));
    number.dataset.latency = node.node_id;
    latency.append(number);
    if (node.latency.status === "MEASURED") {
      const quality = node.latency.rtt_ms < 100 ? "良好" : node.latency.rtt_ms < 300 ? "一般" : "较高";
      latency.append(element("span", `quality${node.latency.rtt_ms >= 100 ? " slow" : ""}`, quality));
      latency.title = `WebSocket Ping/Pong 实测 · ${formatTime(node.latency.measured_at)}\n良好 <100 ms，一般 <300 ms，较高 ≥300 ms`;
    }
    addCell("控制通道 RTT", latency);
    const heartbeat = element("span", "heartbeat");
    heartbeat.dataset.heartbeat = node.node_id;
    heartbeat.textContent = node.connection_status === "OFFLINE" && node.last_seen_at ? `最后在线 ${relativeTime(node.last_seen_at)}` : relativeTime(node.last_seen_at);
    heartbeat.title = formatTime(node.last_seen_at);
    addCell("最近心跳", heartbeat);
    const detail = element("button", "icon-button row-arrow");
    detail.type = "button";
    detail.setAttribute("aria-label", `查看 ${node.name} 的详细信息`);
    detail.append(icon("arrow"));
    detail.addEventListener("click", () => openDetail(node.node_id));
    addCell("详情", detail);
    rows.append(row);
  }
  $("node-list").replaceChildren(rows);
  $("empty").hidden = matching.length !== 0;
  $("empty-title").textContent = snapshot.total ? "没有匹配的节点" : "尚无节点接入";
  $("empty-text").textContent = snapshot.total ? "试试其他关键词，或切换连接状态筛选。" : "Node 登记并连接此 Hub 后，会自动出现在这里。";
  $("clear-filter").hidden = !snapshot.total;
  if (focusedNode) document.querySelector(`[data-node="${CSS.escape(focusedNode)}"]`)?.focus({preventScroll: true});
}

function renderSnapshot() {
  const counts = {online: snapshot.online, total: snapshot.total, free: snapshot.resources.available, busy: snapshot.resources.busy, offline: snapshot.offline};
  for (const [name, value] of Object.entries(counts)) $(`count-${name}`).textContent = value;
  for (const [name, value] of Object.entries({all: snapshot.total, online: snapshot.online, preparing: snapshot.preparing, offline: snapshot.offline})) $(`filter-${name}`).textContent = value;
  $("updated").textContent = `最后更新 ${formatTime(snapshot.snapshot_at)}`;
  $("freshness").textContent = `每 ${snapshot.refresh_interval_seconds} 秒自动更新 · RTT 实测`;
  $("hub-status").className = "hub-status healthy";
  $("hub-status").lastElementChild.textContent = "Hub 正常";
  renderRows();
  if ($("detail").open) renderDetail();
}

function addDetailLine(parent, label, value) {
  const line = element("dl", "detail-line");
  line.append(element("dt", "", label), element("dd", "", value ?? "—"));
  parent.append(line);
}

function detailSection(title) {
  const section = element("section", "detail-section");
  section.append(element("h3", "", title));
  return section;
}

function renderDetail() {
  const node = snapshot.nodes.find((value) => value.node_id === selectedId);
  if (!node) {
    $("detail").close();
    return;
  }
  const expanded = new Set([...$("detail-content").querySelectorAll("details[open]")].map((item) => item.dataset.resource));
  $("detail-title").textContent = node.name;
  const content = document.createDocumentFragment();
  const host = node.capabilities?.host || {};
  content.append(element("p", "detail-meta", node.node_id), element("p", "detail-meta", [hostLabel(node), host.client_version ? `Node ${host.client_version}` : null].filter(Boolean).join(" · ")));
  const states = element("div", "detail-states");
  states.append(connectionState(node), element("span", node.resources.busy ? "amber" : "muted", occupancyLabel(node)));
  content.append(states);
  if (node.capabilities_stale) content.append(element("p", "notice", node.connection_status === "OFFLINE" ? "节点已离线。下方能力为历史快照，不代表当前可用；资源占用未知。" : "正在等待当前连接的能力上报，历史快照不代表当前可用。"));
  if (document.body.classList.contains("stale")) content.append(element("p", "notice", "连接暂时中断，下方为上次成功获取的数据。"));
  const metrics = element("div", "detail-metrics");
  for (const [label, value] of [["控制通道 RTT", latencyText(node)], ["最近心跳", relativeTime(node.last_seen_at)]]) {
    const metric = element("div", "detail-metric");
    metric.append(element("span", "", label), element("strong", "", value));
    metrics.append(metric);
  }
  content.append(metrics);
  const connection = detailSection("连接与主机");
  addDetailLine(connection, "主机名", host.hostname);
  addDetailLine(connection, "连接代次", node.connection_generation);
  addDetailLine(connection, "本次心跳数", node.heartbeat_count);
  addDetailLine(connection, "最近上报", formatTime(node.last_seen_at));
  addDetailLine(connection, "能力快照", formatTime(node.capabilities_observed_at));
  addDetailLine(connection, "RTT 采样", node.latency.measured_at ? formatTime(node.latency.measured_at) : "暂无有效测量");
  addDetailLine(connection, "Python", host.python_version);
  content.append(connection);
  const resources = detailSection(`执行资源 · ${node.resources.total}`);
  if (!node.resources.total) resources.append(element("p", "detail-meta", "尚无执行资源上报。"));
  for (const resource of node.capabilities?.resources || []) {
    const item = element("div", "resource-detail");
    const heading = element("div", "resource-detail-head");
    const occupancy = node.connection_status !== "ONLINE" || resource.occupancy === "UNKNOWN" ? "占用未知" : resource.occupancy === "BUSY" ? "已占用" : "未占用";
    heading.append(element("strong", "", resource.resource_id), element("span", resource.occupancy === "BUSY" && node.connection_status === "ONLINE" ? "amber" : "muted", occupancy));
    item.append(heading, element("p", "detail-meta", `${backendNames[resource.backend] || resource.backend} · ${resource.kind} · ${node.capabilities_stale ? "历史就绪状态：" : ""}${readinessNames[resource.readiness]}`));
    const methods = element("details");
    methods.dataset.resource = resource.resource_id;
    methods.open = expanded.has(resource.resource_id);
    methods.append(element("summary", "detail-meta", `支持方法 ${resource.methods.length} 项 · ${resource.tool} API v${resource.tool_api_version}`), element("p", "method-list", resource.methods.join(" · ") || "尚未声明方法"));
    item.append(methods);
    resources.append(item);
  }
  content.append(resources);
  const backends = detailSection("后端能力与安装信息");
  if (!node.capabilities?.backends.length) backends.append(element("p", "detail-meta", "尚未上报后端能力。"));
  for (const backend of node.capabilities?.backends || []) {
    const row = element("div", "backend-row");
    const name = element("div", "", backendNames[backend.name] || backend.name);
    const install = backend.installed === true ? "已安装" : backend.installed === false ? "未安装" : "安装状态未探测";
    name.append(element("small", "", `${install}${backend.runtime_version ? ` · ${backend.runtime_version}` : ""}`));
    row.append(name, element("span", backend.coverage_status === "SUPPORTED" ? "green" : "muted", `${node.capabilities_stale ? "历史：" : ""}${coverageNames[backend.coverage_status]}`));
    backends.append(row);
  }
  content.append(backends, element("p", "detail-footnote", `Hub ${snapshot.hub_version} · 仅展示 Node 已报告的信息。安装了某个工具不等于已支持执行。RTT 是控制连接 Ping/Pong 的往返耗时，默认约 20 秒测量一次；超过 60 秒不再作为实时值显示。`));
  $("detail-content").replaceChildren(content);
}

function openDetail(nodeId) {
  selectedId = nodeId;
  renderDetail();
  $("detail").showModal();
  renderRows();
}

function setNotice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function logout(message = "") {
  generation++;
  token = "";
  snapshot = null;
  clearTimeout(timer);
  pending?.abort();
  pending = null;
  if ($("detail").open) $("detail").close();
  selectedId = null;
  $("node-list").replaceChildren();
  $("detail-content").replaceChildren();
  document.body.classList.remove("stale");
  $("overview").hidden = true;
  $("login").hidden = false;
  $("refresh").hidden = true;
  $("logout").hidden = true;
  $("updated").textContent = "节点监控";
  $("hub-status").className = "hub-status";
  $("hub-status").lastElementChild.textContent = "等待验证";
  $("login-error").textContent = message;
  $("login-error").hidden = !message;
  $("login-button").disabled = false;
  $("token").value = "";
  $("token").focus();
}

function clearLinkToken() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("token")) return;
  url.searchParams.delete("token");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

async function refresh() {
  if (!token || pending) return;
  clearTimeout(timer);
  const current = generation;
  const controller = new AbortController();
  pending = controller;
  const deadline = setTimeout(() => controller.abort(), 8000);
  $("refresh").disabled = true;
  try {
    const response = await fetch("/dashboard/api/nodes", {headers: {Authorization: `Bearer ${token}`}, cache: "no-store", signal: controller.signal, credentials: "omit"});
    if (current !== generation) return;
    if (response.status === 401) {
      clearLinkToken();
      logout("只读口令无效或已更换，请重新输入。");
      return;
    }
    if (!response.ok) throw new Error("unavailable");
    const data = await response.json();
    if (current !== generation) return;
    snapshot = data;
    receivedAt = performance.now();
    $("overview").hidden = false;
    $("login").hidden = true;
    $("refresh").hidden = false;
    $("logout").hidden = false;
    $("login-button").disabled = false;
    document.body.classList.remove("stale");
    setNotice();
    renderSnapshot();
  } catch {
    if (current !== generation) return;
    if (!snapshot) {
      logout("暂时无法连接 Hub，请检查服务地址和网络后重试。");
      return;
    }
    document.body.classList.add("stale");
    $("hub-status").className = "hub-status degraded";
    $("hub-status").lastElementChild.textContent = "连接中断";
    setNotice(`暂时无法更新。当前展示的是 ${formatTime(snapshot.snapshot_at)} 的历史数据，正在自动重连。`);
    if ($("detail").open) renderDetail();
  } finally {
    clearTimeout(deadline);
    if (pending === controller) pending = null;
    $("refresh").disabled = false;
    if (token && current === generation && !document.hidden) timer = setTimeout(refresh, (snapshot?.refresh_interval_seconds || 5) * 1000);
  }
}

function login(value) {
  $("token").value = "";
  if (!value) return;
  token = value;
  generation++;
  $("login-error").hidden = true;
  $("login-button").disabled = true;
  refresh();
}

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  login($("token").value.trim());
});
$("refresh").addEventListener("click", refresh);
$("logout").addEventListener("click", () => {
  clearLinkToken();
  logout();
});
$("search").addEventListener("input", (event) => {
  search = event.target.value.trim().toLocaleLowerCase();
  renderRows();
});
$("filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-status]");
  if (!button) return;
  filter = button.dataset.status;
  for (const item of $("filters").querySelectorAll("button")) {
    item.classList.toggle("active", item === button);
    item.setAttribute("aria-pressed", String(item === button));
  }
  renderRows();
});
$("clear-filter").addEventListener("click", () => {
  search = "";
  $("search").value = "";
  $("filters").querySelector("button[data-status='ALL']").click();
});
$("close-detail").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("close", () => {
  const previousId = selectedId;
  selectedId = null;
  renderRows();
  if (previousId) document.querySelector(`[data-node="${CSS.escape(previousId)}"]`)?.focus({preventScroll: true});
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(timer);
  else refresh();
});
window.addEventListener("pagehide", () => {
  logout();
});
setInterval(() => {
  if (!snapshot || document.hidden) return;
  const byId = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
  for (const item of document.querySelectorAll("[data-heartbeat]")) {
    const node = byId.get(item.dataset.heartbeat);
    item.textContent = node.connection_status === "OFFLINE" && node.last_seen_at ? `最后在线 ${relativeTime(node.last_seen_at)}` : relativeTime(node.last_seen_at);
  }
  for (const item of document.querySelectorAll("[data-latency]")) {
    item.textContent = latencyText(byId.get(item.dataset.latency));
    const quality = item.parentElement.querySelector(".quality");
    if (quality) quality.hidden = item.textContent === "已过期";
  }
}, 1000);

const pageUrl = new URL(window.location.href);
if (pageUrl.searchParams.has("token")) {
  login(pageUrl.searchParams.get("token").trim());
}

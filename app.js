const state = { tickets: [], selectedId: null, stats: null };

const elements = {
  inboxView: document.querySelector("#inbox-view"),
  workflowView: document.querySelector("#workflow-view"),
  pageTitle: document.querySelector("#page-title"),
  ticketList: document.querySelector("#ticket-list"),
  ticketCount: document.querySelector("#ticket-count"),
  urgentCount: document.querySelector("#urgent-count"),
  approvalCount: document.querySelector("#approval-count"),
  resolvedCount: document.querySelector("#resolved-count"),
  openLabel: document.querySelector("#open-label"),
  automationProvider: document.querySelector("#automation-provider"),
  automationSummary: document.querySelector("#automation-summary"),
  healthLabel: document.querySelector("#health-label"),
  customerName: document.querySelector("#customer-name"),
  companyName: document.querySelector("#company-name"),
  ticketStatus: document.querySelector("#ticket-status"),
  ticketId: document.querySelector("#ticket-id"),
  accountValue: document.querySelector("#account-value"),
  activeUsers: document.querySelector("#active-users"),
  workflowState: document.querySelector("#workflow-state"),
  messages: document.querySelector("#messages"),
  replyCopy: document.querySelector("#reply-copy"),
  replyTo: document.querySelector("#reply-to"),
  confidenceValue: document.querySelector("#confidence-value"),
  triageProvider: document.querySelector("#triage-provider"),
  intentValue: document.querySelector("#intent-value"),
  priorityValue: document.querySelector("#priority-value"),
  sentimentValue: document.querySelector("#sentiment-value"),
  routeValue: document.querySelector("#route-value"),
  riskReason: document.querySelector("#risk-reason"),
  actionList: document.querySelector("#action-list"),
  sourceList: document.querySelector("#source-list"),
  sourceCount: document.querySelector("#source-count"),
  approvalPanel: document.querySelector("#approval-panel"),
  workflowStatus: document.querySelector("#workflow-status"),
  workflowOutput: document.querySelector("#workflow-output"),
  toast: document.querySelector("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.ok) return response.json();
  let message = `Request failed (${response.status})`;
  try {
    message = (await response.json()).detail || message;
  } catch {
    // Keep the HTTP status when an upstream did not return JSON.
  }
  throw new Error(message);
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function initials(name) {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function money(value) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function setView(view) {
  const showWorkflow = view === "workflow";
  elements.inboxView.hidden = showWorkflow;
  elements.workflowView.hidden = !showWorkflow;
  elements.pageTitle.textContent = showWorkflow ? "Automation workflow" : "Support inbox";
  document.querySelectorAll("[data-view-button]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewButton === view);
  });
}

function showToast(title, message) {
  elements.toast.querySelector("strong").textContent = title;
  elements.toast.querySelector("small").textContent = message;
  elements.toast.classList.add("show");
  window.setTimeout(() => elements.toast.classList.remove("show"), 3500);
}

function renderStats() {
  const stats = state.stats;
  elements.ticketCount.textContent = String(stats.tickets);
  elements.urgentCount.textContent = String(
    state.tickets.filter((ticket) => ticket.priority === "Urgent").length,
  );
  elements.approvalCount.textContent = String(stats.needs_approval);
  elements.resolvedCount.textContent = String(stats.resolved);
  elements.openLabel.textContent = `${stats.tickets - stats.resolved} open`;
  elements.automationProvider.textContent = `${stats.automation_provider} automation`;
  elements.automationSummary.textContent =
    `${stats.needs_approval} awaiting approval · ${stats.resolved} resolved`;
  elements.triageProvider.textContent = `${stats.automation_provider} structured output`;
}

function renderTickets() {
  elements.ticketList.replaceChildren();
  state.tickets.forEach((ticket, index) => {
    const card = node("article", `ticket${ticket.id === state.selectedId ? " selected" : ""}`);
    card.dataset.ticketId = ticket.id;
    const top = node("div", "ticket-topline");
    top.append(
      node("div", `avatar ${index % 2 ? "avatar-cyan" : "avatar-indigo"}`, initials(ticket.customer_name)),
      node("span", "ticket-time", ticket.status === "resolved" ? "Done" : "Open"),
    );
    const tags = node("div", "ticket-tags");
    tags.append(
      node("span", `tag ${ticket.priority === "Urgent" ? "danger" : "neutral"}`, ticket.priority),
      node("span", "tag violet", ticket.route),
      node("span", "ai-mark", "✦ Triaged"),
    );
    card.append(
      top,
      node("strong", "", ticket.subject),
      node("p", "", ticket.body),
      tags,
    );
    elements.ticketList.append(card);
  });
}

function renderMessage(ticket) {
  elements.messages.replaceChildren();
  const separator = node("div", "date-separator");
  separator.append(node("span", "", "Incoming request"));
  const message = node("article", "message customer-message");
  const meta = node("div", "message-meta");
  meta.append(
    node("strong", "", ticket.customer_name),
    node("span", "", "via API intake"),
    node("time", "", new Date(ticket.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),
  );
  message.append(meta, node("p", "", ticket.body));
  const event = node("div", "system-event");
  event.append(node("span", "sparkle", "✦"));
  const eventCopy = node("div");
  eventCopy.append(
    node("strong", "", "Automation triage completed"),
    node("span", "", `${ticket.intent} · ${ticket.priority} · ${ticket.route}`),
  );
  event.append(eventCopy);
  elements.messages.append(separator, message, event);
  if (ticket.status === "resolved") {
    const sent = node("article", "message sent-message");
    const sentMeta = node("div", "message-meta");
    sentMeta.append(
      node("strong", "", "Local reviewer"),
      node("span", "", "approved generated draft"),
      node("span", "sent-label", "Approved ✓"),
    );
    sent.append(sentMeta, node("p", "", ticket.draft));
    elements.messages.append(sent);
  }
}

function renderActions(ticket) {
  elements.actionList.replaceChildren();
  ticket.actions.forEach((action) => {
    const item = node("div", "action-item");
    const copy = node("div");
    copy.append(node("strong", "", action.label), node("small", "", action.system));
    item.append(
      node("span", "check-circle", action.status === "completed" ? "✓" : "·"),
      copy,
      node("span", "ready", action.status === "completed" ? "Done" : "Pending"),
    );
    elements.actionList.append(item);
  });
}

function renderSources(ticket) {
  elements.sourceList.replaceChildren();
  elements.sourceCount.textContent =
    `${ticket.sources.length} polic${ticket.sources.length === 1 ? "y" : "ies"}`;
  ticket.sources.forEach((source) => {
    const card = node("div", "source-card");
    const copy = node("div");
    copy.append(
      node("strong", "", source.title),
      node("span", "", `${source.section} · ${source.excerpt}`),
    );
    card.append(
      node("div", "source-icon", "POL"),
      copy,
      node("span", "source-score", `${Math.round(source.score * 100)}%`),
    );
    elements.sourceList.append(card);
  });
}

function renderApproval(ticket) {
  elements.approvalPanel.replaceChildren();
  if (ticket.status === "resolved") {
    const banner = node("div", "approved-banner");
    const copy = node("div");
    copy.append(
      node("strong", "", "Actions completed after approval"),
      node("small", "", "Billing, case history and notification outbox were updated"),
    );
    banner.append(node("span", "", "✓"), copy);
    elements.approvalPanel.append(banner);
    return;
  }
  elements.approvalPanel.append(node("div", "approval-note", "Human approval gates every side effect"));
  const buttons = node("div", "approval-buttons");
  const inspect = node("a", "secondary api-link", "Inspect API");
  inspect.href = "/docs";
  inspect.target = "_blank";
  const approve = node("button", "primary", "Approve & execute");
  approve.id = "approve-button";
  buttons.append(inspect, approve);
  elements.approvalPanel.append(buttons);
}

function renderSelected() {
  const ticket = state.tickets.find((candidate) => candidate.id === state.selectedId);
  if (!ticket) return;
  elements.customerName.textContent = ticket.customer_name;
  elements.companyName.textContent = `${ticket.company} · Sample account`;
  elements.ticketStatus.textContent =
    ticket.status === "resolved" ? "Resolved" : ticket.priority;
  elements.ticketStatus.className =
    ticket.status === "resolved" ? "status-pill tag success" : "status-pill urgent";
  elements.ticketId.textContent = ticket.id;
  elements.accountValue.textContent = `${money(ticket.arr_usd)} ARR`;
  elements.activeUsers.textContent = `${ticket.active_users} users`;
  elements.workflowState.textContent = ticket.status.replaceAll("_", " ");
  elements.replyCopy.textContent = ticket.draft;
  elements.replyTo.textContent = `To: ${ticket.customer_name}`;
  elements.confidenceValue.textContent = `${Math.round(ticket.confidence * 100)}% confidence`;
  elements.intentValue.textContent = ticket.intent;
  elements.priorityValue.textContent = ticket.priority;
  elements.sentimentValue.textContent = ticket.sentiment;
  elements.routeValue.textContent = ticket.route;
  elements.riskReason.textContent = ticket.risk_reason;
  elements.workflowStatus.textContent =
    ticket.status === "resolved" ? "Completed" : "Awaiting review";
  elements.workflowOutput.textContent = JSON.stringify(
    {
      status: ticket.status,
      side_effects: ticket.status === "resolved" ? "completed" : "pending",
      audit_log: true,
    },
    null,
    2,
  );
  renderMessage(ticket);
  renderActions(ticket);
  renderSources(ticket);
  renderApproval(ticket);
  renderTickets();
}

async function refresh() {
  const [tickets, stats] = await Promise.all([api("/api/tickets"), api("/api/stats")]);
  state.tickets = tickets;
  state.stats = stats;
  if (!state.selectedId || !tickets.some((ticket) => ticket.id === state.selectedId)) {
    state.selectedId = tickets[0]?.id || null;
  }
  renderStats();
  renderSelected();
}

document.querySelectorAll("[data-view-button]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.viewButton));
});

elements.ticketList.addEventListener("click", (event) => {
  const ticket = event.target.closest("[data-ticket-id]");
  if (!ticket) return;
  state.selectedId = ticket.dataset.ticketId;
  renderSelected();
});

elements.approvalPanel.addEventListener("click", async (event) => {
  if (event.target.id !== "approve-button") return;
  event.target.disabled = true;
  event.target.textContent = "Executing…";
  try {
    await api(`/api/tickets/${state.selectedId}/approve`, { method: "POST" });
    await refresh();
    showToast("Approval completed", "The draft and all local adapter actions were committed.");
  } catch (error) {
    event.target.disabled = false;
    event.target.textContent = "Approve & execute";
    showToast("Approval failed", error.message);
  }
});

async function initialize() {
  try {
    const health = await api("/api/health");
    elements.healthLabel.textContent = "Workflow API healthy";
    await refresh();
    elements.automationProvider.textContent = `${health.automation_provider} automation`;
  } catch (error) {
    elements.healthLabel.textContent = "API unavailable";
    elements.automationSummary.textContent = error.message;
  }
}

initialize();

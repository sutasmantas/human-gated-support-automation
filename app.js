const state = {
  tickets: [],
  stats: null,
  workflow: [],
  selectedId: null,
  events: new Map(),
  filter: "all",
  query: "",
  view: "cases",
  intelTab: "work",
};

const elements = Object.fromEntries(
  [
    "nav-case-count",
    "nav-run-alerts",
    "health-dot",
    "health-label",
    "provider-label",
    "queue-summary",
    "page-context",
    "page-title",
    "cases-view",
    "workflow-view",
    "runs-view",
    "queue-count",
    "case-search",
    "case-list",
    "customer-avatar",
    "customer-name",
    "case-status",
    "company-name",
    "case-id",
    "account-value",
    "route-value",
    "priority-value",
    "active-users",
    "confidence-value",
    "message-author",
    "message-time",
    "case-subject",
    "case-body",
    "triage-summary",
    "copy-draft",
    "draft-copy",
    "draft-state",
    "confidence-chip",
    "evidence-count",
    "risk-heading",
    "risk-reason",
    "intent-value",
    "sentiment-value",
    "action-count",
    "action-list",
    "source-list",
    "case-timeline",
    "review-bar",
    "workflow-graph",
    "workflow-provider",
    "run-list",
    "run-title",
    "run-subtitle",
    "run-status",
    "run-case",
    "run-route",
    "run-actions",
    "run-approved",
    "run-timeline",
    "receipt-list",
    "reject-dialog",
    "reject-note",
    "confirm-reject",
    "toast",
  ].map((id) => [
    id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()),
    document.getElementById(id),
  ]),
);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.ok) return response.json();
  let message = `Request failed (${response.status})`;
  try {
    message = (await response.json()).detail || message;
  } catch {
    // Retain the status message when an upstream does not return JSON.
  }
  throw new Error(message);
}

function create(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function initials(name = "") {
  return (
    name
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "—"
  );
}

function money(value, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function shortTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function shortDate(value) {
  return new Date(value).toLocaleDateString([], { month: "short", day: "numeric" });
}

function sentenceStatus(status) {
  const labels = {
    needs_approval: "Needs approval",
    draft_ready: "Draft ready",
    action_failed: "Action failed",
    dead_letter: "Dead letter",
    resolved: "Resolved",
    rejected: "Rejected",
  };
  return labels[status] || status.replaceAll("_", " ");
}

function statusClass(status) {
  if (status === "resolved") return "success";
  if (status === "rejected" || status === "dead_letter") return "danger";
  if (status === "action_failed") return "warning";
  if (status === "needs_approval") return "review";
  return "neutral";
}

function selectedTicket() {
  return state.tickets.find((ticket) => ticket.id === state.selectedId) || null;
}

function showToast(title, message) {
  elements.toast.replaceChildren(create("strong", "", title), create("span", "", message));
  elements.toast.classList.add("show");
  window.setTimeout(() => elements.toast.classList.remove("show"), 3200);
}

function setView(view, updateHash = true) {
  state.view = view;
  const config = {
    cases: ["Customer operations", "Case workspace"],
    workflow: ["Automation design", "Published workflow"],
    runs: ["Reliability and audit", "Run history"],
  };
  ["cases", "workflow", "runs"].forEach((name) => {
    elements[`${name}View`].hidden = name !== view;
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  [elements.pageContext.textContent, elements.pageTitle.textContent] = config[view];
  if (updateHash) history.replaceState(null, "", `#${view}`);
  if (view === "runs") renderRuns();
}

function setIntelTab(tab) {
  state.intelTab = tab;
  document.querySelectorAll("[data-intel-tab]").forEach((button) => {
    const active = button.dataset.intelTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-intel-pane]").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.intelPane === tab);
  });
}

function ticketMatches(ticket) {
  const statusGroups = {
    all: () => true,
    review: () => ["needs_approval", "draft_ready"].includes(ticket.status),
    exception: () => ["action_failed", "dead_letter", "rejected"].includes(ticket.status),
    resolved: () => ticket.status === "resolved",
  };
  const query = state.query.trim().toLowerCase();
  const text = `${ticket.subject} ${ticket.company} ${ticket.customer_name} ${ticket.route}`.toLowerCase();
  return statusGroups[state.filter](ticket) && (!query || text.includes(query));
}

function renderStats() {
  const exceptions = state.tickets.filter((ticket) =>
    ["action_failed", "dead_letter"].includes(ticket.status),
  ).length;
  const pending = state.tickets.filter((ticket) =>
    ["needs_approval", "draft_ready"].includes(ticket.status),
  ).length;
  elements.navCaseCount.textContent = String(state.tickets.length);
  elements.navRunAlerts.hidden = exceptions === 0;
  elements.navRunAlerts.textContent = String(exceptions);
  elements.queueSummary.textContent = `${pending} awaiting review · ${state.stats.resolved} completed`;
  elements.providerLabel.textContent = `${state.stats.automation_provider} automation`;
  elements.workflowProvider.textContent = `${state.stats.automation_provider} structured output`;
}

function renderQueue() {
  const visible = state.tickets.filter(ticketMatches);
  elements.queueCount.textContent = String(visible.length);
  elements.caseList.replaceChildren();
  if (!visible.length) {
    const empty = create("div", "empty-state");
    empty.append(
      create("strong", "", "No cases match this view"),
      create("p", "", "Change the filter or search term to return to the queue."),
    );
    elements.caseList.append(empty);
    return;
  }

  visible.forEach((ticket) => {
    const button = create(
      "button",
      `case-card${ticket.id === state.selectedId ? " selected" : ""}`,
    );
    button.type = "button";
    button.dataset.ticketId = ticket.id;

    const top = create("div", "case-card-top");
    const person = create("div", "case-person");
    person.append(
      create("span", "mini-avatar", initials(ticket.customer_name)),
      create("strong", "", ticket.company),
    );
    top.append(person, create("time", "", shortTime(ticket.created_at)));

    const subject = create("h3", "", ticket.subject);
    const summary = create("p", "", ticket.body);
    const footer = create("div", "case-card-footer");
    footer.append(
      create("span", `status-label ${statusClass(ticket.status)}`, sentenceStatus(ticket.status)),
      create("span", "route-label", ticket.route),
    );
    button.append(top, subject, summary, footer);
    elements.caseList.append(button);
  });
}

function renderActions(ticket) {
  elements.actionList.replaceChildren();
  elements.actionCount.textContent = String(ticket.actions.length);
  ticket.actions.forEach((action, index) => {
    const item = create("article", `action-row ${action.status}`);
    const stateMark = create(
      "span",
      "action-state",
      action.status === "completed" ? "✓" : action.status === "failed" ? "!" : String(index + 1),
    );
    const copy = create("div", "action-copy");
    copy.append(create("strong", "", action.label), create("span", "", action.system));
    if (action.result || action.last_error) {
      copy.append(create("small", "", action.result || action.last_error));
    }
    const meta = create(
      "span",
      "action-meta",
      action.attempts ? `${action.attempts} attempt${action.attempts === 1 ? "" : "s"}` : "Ready",
    );
    item.append(stateMark, copy, meta);
    elements.actionList.append(item);
  });
}

function renderSources(ticket) {
  elements.sourceList.replaceChildren();
  elements.evidenceCount.textContent = String(ticket.sources.length);
  if (!ticket.sources.length) {
    const empty = create("div", "empty-state compact");
    empty.append(
      create("strong", "", "No policy passage attached"),
      create("p", "", "The draft should remain in review until a suitable source is available."),
    );
    elements.sourceList.append(empty);
    return;
  }
  ticket.sources.forEach((source, index) => {
    const card = create("article", "source-card");
    const header = create("header");
    header.append(
      create("span", "source-number", String(index + 1).padStart(2, "0")),
      create("span", "source-score", `${Math.round(source.score * 100)}% match`),
    );
    card.append(
      header,
      create("h3", "", source.title),
      create("span", "source-section", source.section),
      create("p", "", source.excerpt),
    );
    elements.sourceList.append(card);
  });
}

function eventLabel(type) {
  const labels = {
    "ticket.created": "Case received and routed",
    "approval.approved": "Human approval recorded",
    "approval.rejected": "Proposal rejected",
    "actions.completed": "All side effects completed",
    "actions.failed": "Adapter execution failed",
    "actions.dead_lettered": "Run moved to dead letter",
  };
  return labels[type] || type.replaceAll(".", " ");
}

function renderTimeline(target, events) {
  target.replaceChildren();
  if (!events.length) {
    target.append(create("div", "empty-state compact", "No events recorded."));
    return;
  }
  events.forEach((event) => {
    const item = create("article", `timeline-item ${event.event_type.replaceAll(".", "-")}`);
    const marker = create("span", "timeline-marker");
    const copy = create("div");
    copy.append(
      create("strong", "", eventLabel(event.event_type)),
      create("p", "", event.detail),
      create("time", "", `${shortDate(event.created_at)} · ${shortTime(event.created_at)}`),
    );
    item.append(marker, copy);
    target.append(item);
  });
}

async function ensureEvents(ticketId) {
  if (!state.events.has(ticketId)) {
    state.events.set(ticketId, await api(`/api/tickets/${ticketId}/events`));
  }
  return state.events.get(ticketId);
}

function appendButton(target, label, className, action) {
  const button = create("button", `button ${className}`, label);
  button.type = "button";
  button.dataset.action = action;
  target.append(button);
}

function renderReview(ticket) {
  elements.reviewBar.replaceChildren();
  const message = create("div", "review-message");
  const controls = create("div", "review-actions");

  if (ticket.status === "resolved") {
    message.append(
      create("strong", "", "Completed safely"),
      create("span", "", "Reply and adapter receipts are recorded in the audit trail."),
    );
    elements.reviewBar.className = "review-bar completed";
  } else if (ticket.status === "rejected") {
    message.append(
      create("strong", "", "Proposal rejected"),
      create("span", "", "The reason is retained in the case timeline."),
    );
    elements.reviewBar.className = "review-bar rejected";
  } else if (ticket.status === "action_failed") {
    message.append(
      create("strong", "", "One adapter needs attention"),
      create("span", "", "Completed actions will not run again."),
    );
    appendButton(controls, "Retry failed action", "primary", "retry");
    elements.reviewBar.className = "review-bar exception";
  } else if (ticket.status === "dead_letter") {
    message.append(
      create("strong", "", "Retry budget exhausted"),
      create("span", "", "Manual operator intervention is required."),
    );
    elements.reviewBar.className = "review-bar exception";
  } else {
    message.append(
      create("strong", "", "Human decision required"),
      create("span", "", `${ticket.actions.length} proposed action${ticket.actions.length === 1 ? "" : "s"} remain blocked.`),
    );
    appendButton(controls, "Reject", "secondary", "reject");
    appendButton(controls, "Approve and execute", "primary", "approve");
    elements.reviewBar.className = "review-bar";
  }
  elements.reviewBar.append(message, controls);
}

async function renderSelected() {
  const ticket = selectedTicket();
  if (!ticket) return;
  elements.customerAvatar.textContent = initials(ticket.customer_name);
  elements.customerName.textContent = ticket.customer_name;
  elements.caseStatus.textContent = sentenceStatus(ticket.status);
  elements.caseStatus.className = `status-badge ${statusClass(ticket.status)}`;
  elements.companyName.textContent = ticket.company;
  elements.caseId.textContent = ticket.id;
  elements.accountValue.textContent = `${money(ticket.arr_usd)} ARR`;
  elements.routeValue.textContent = ticket.route;
  elements.priorityValue.textContent = ticket.priority;
  elements.activeUsers.textContent = String(ticket.active_users);
  elements.confidenceValue.textContent = `${Math.round(ticket.confidence * 100)}%`;
  elements.messageAuthor.textContent = ticket.customer_name;
  elements.messageTime.textContent = shortTime(ticket.created_at);
  elements.caseSubject.textContent = ticket.subject;
  elements.caseBody.textContent = ticket.body;
  elements.triageSummary.textContent =
    `${ticket.intent} · ${ticket.priority} · routed to ${ticket.route}`;
  elements.draftCopy.value = ticket.draft;
  elements.draftState.textContent =
    ticket.status === "resolved" ? "Approved and recorded" : "Not yet approved";
  elements.confidenceChip.textContent = `${Math.round(ticket.confidence * 100)}%`;
  elements.riskHeading.textContent =
    ticket.priority === "Urgent" ? "Consequential account action" : "Review before execution";
  elements.riskReason.textContent = ticket.risk_reason;
  elements.intentValue.textContent = ticket.intent;
  elements.sentimentValue.textContent = ticket.sentiment;
  renderActions(ticket);
  renderSources(ticket);
  renderReview(ticket);
  const events = await ensureEvents(ticket.id);
  renderTimeline(elements.caseTimeline, events);
  renderQueue();
}

function renderWorkflow() {
  elements.workflowGraph.replaceChildren();
  state.workflow.forEach((step, index) => {
    const node = create("article", `workflow-step ${step.kind}`);
    const header = create("header");
    header.append(
      create("span", "step-number", String(index + 1).padStart(2, "0")),
      create("span", "step-kind", step.kind),
    );
    node.append(header, create("h3", "", step.name), create("p", "", step.description));
    if (index < state.workflow.length - 1) node.append(create("span", "step-connector"));
    elements.workflowGraph.append(node);
  });
}

function renderRunList() {
  elements.runList.replaceChildren();
  state.tickets.forEach((ticket) => {
    const button = create(
      "button",
      `run-row${ticket.id === state.selectedId ? " selected" : ""}`,
    );
    button.type = "button";
    button.dataset.runId = ticket.id;
    const copy = create("div");
    copy.append(create("strong", "", ticket.subject), create("span", "", ticket.id));
    button.append(
      create("span", `run-state-dot ${statusClass(ticket.status)}`),
      copy,
      create("span", `status-label ${statusClass(ticket.status)}`, sentenceStatus(ticket.status)),
    );
    elements.runList.append(button);
  });
}

async function renderRuns() {
  renderRunList();
  const ticket = selectedTicket();
  if (!ticket) return;
  const events = await ensureEvents(ticket.id);
  elements.runTitle.textContent = ticket.subject;
  elements.runSubtitle.textContent = `${ticket.company} · created ${shortDate(ticket.created_at)} at ${shortTime(ticket.created_at)}`;
  elements.runStatus.textContent = sentenceStatus(ticket.status);
  elements.runStatus.className = `status-badge ${statusClass(ticket.status)}`;
  elements.runCase.textContent = ticket.id;
  elements.runRoute.textContent = ticket.route;
  elements.runActions.textContent = `${ticket.actions.filter((action) => action.status === "completed").length}/${ticket.actions.length} completed`;
  elements.runApproved.textContent = ticket.approved_at
    ? `${shortDate(ticket.approved_at)} · ${shortTime(ticket.approved_at)}`
    : "Not approved";
  renderTimeline(elements.runTimeline, events);
  elements.receiptList.replaceChildren();
  ticket.actions.forEach((action) => {
    const receipt = create("article", `receipt-row ${action.status}`);
    const header = create("div");
    header.append(
      create("strong", "", action.label),
      create("span", `status-label ${action.status === "completed" ? "success" : action.status === "failed" ? "danger" : "neutral"}`, action.status),
    );
    receipt.append(
      header,
      create("p", "", action.result || action.last_error || "Execution is blocked pending approval."),
      create("span", "", `${action.system} · ${action.attempts || 0} attempts`),
    );
    elements.receiptList.append(receipt);
  });
}

async function refresh(selectId = state.selectedId) {
  const [tickets, stats] = await Promise.all([api("/api/tickets"), api("/api/stats")]);
  state.tickets = tickets;
  state.stats = stats;
  state.selectedId =
    selectId && tickets.some((ticket) => ticket.id === selectId) ? selectId : tickets[0]?.id;
  renderStats();
  await renderSelected();
  if (state.view === "runs") await renderRuns();
}

async function performAction(action) {
  const ticket = selectedTicket();
  if (!ticket) return;
  const active = document.querySelector(`[data-action="${action}"]`);
  if (active) active.disabled = true;
  try {
    if (action === "approve") {
      await api(`/api/tickets/${ticket.id}/approve`, { method: "POST" });
      showToast("Actions completed", "The approved reply and adapter receipts are now audited.");
    } else if (action === "retry") {
      await api(`/api/tickets/${ticket.id}/retry`, { method: "POST" });
      showToast("Retry completed", "Only the failed adapter was executed again.");
    }
    state.events.delete(ticket.id);
    await refresh(ticket.id);
  } catch (error) {
    showToast("Action failed", error.message);
    if (active) active.disabled = false;
  }
}

async function rejectSelected() {
  const ticket = selectedTicket();
  if (!ticket) return;
  elements.confirmReject.disabled = true;
  try {
    await api(`/api/tickets/${ticket.id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: "reject", note: elements.rejectNote.value.trim() }),
    });
    elements.rejectDialog.close();
    elements.rejectNote.value = "";
    state.events.delete(ticket.id);
    await refresh(ticket.id);
    showToast("Proposal rejected", "The reviewer reason was added to the audit trail.");
  } catch (error) {
    showToast("Rejection failed", error.message);
  } finally {
    elements.confirmReject.disabled = false;
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((candidate) => {
      candidate.classList.toggle("active", candidate === button);
    });
    renderQueue();
  });
});

document.querySelectorAll("[data-intel-tab]").forEach((button) => {
  button.addEventListener("click", () => setIntelTab(button.dataset.intelTab));
});

elements.caseSearch.addEventListener("input", () => {
  state.query = elements.caseSearch.value;
  renderQueue();
});

elements.caseList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-ticket-id]");
  if (!button) return;
  state.selectedId = button.dataset.ticketId;
  await renderSelected();
});

elements.runList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-run-id]");
  if (!button) return;
  state.selectedId = button.dataset.runId;
  await renderRuns();
});

elements.reviewBar.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "reject") {
    elements.rejectDialog.showModal();
    elements.rejectNote.focus();
    return;
  }
  await performAction(action);
});

elements.confirmReject.addEventListener("click", rejectSelected);

elements.copyDraft.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(elements.draftCopy.value);
    showToast("Draft copied", "The grounded response is ready to paste.");
  } catch {
    elements.draftCopy.select();
    showToast("Draft selected", "Copy the selected response with your keyboard shortcut.");
  }
});

window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (["cases", "workflow", "runs"].includes(view)) setView(view, false);
});

async function initialize() {
  try {
    const [health, workflow] = await Promise.all([api("/api/health"), api("/api/workflow")]);
    state.workflow = workflow;
    elements.healthLabel.textContent = "All systems operational";
    elements.healthDot.classList.add("healthy");
    elements.providerLabel.textContent = `${health.automation_provider} automation`;
    renderWorkflow();
    const initialView = ["cases", "workflow", "runs"].includes(location.hash.slice(1))
      ? location.hash.slice(1)
      : "cases";
    setView(initialView, false);
    await refresh();
  } catch (error) {
    elements.healthLabel.textContent = "Service unavailable";
    elements.queueSummary.textContent = error.message;
    showToast("Relay could not start", error.message);
  }
}

initialize();

(() => {
  const sources = [
    { title: "Enterprise billing policy", section: "Grace periods", excerpt: "Enterprise accounts may receive one seven-day service hold after a failed renewal when Finance confirms that a payment update is in progress.", score: 0.98 },
    { title: "Failed renewal playbook", section: "Escalation and communication", excerpt: "Support must create a renewal case, notify Billing Operations and obtain human approval before promising continued service to an account above 25,000 USD ARR.", score: 0.94 },
  ];
  const actions = (status) => [
    { id: "billing-hold", kind: "billing_hold", label: "Apply 7-day billing hold", system: "Billing adapter", status, result: status === "completed" ? "Seven-day hold recorded" : null, attempts: status === "completed" ? 1 : 0, last_error: null },
    { id: "case-update", kind: "case_update", label: "Update renewal case", system: "CRM adapter", status, result: status === "completed" ? "Case event recorded" : null, attempts: status === "completed" ? 1 : 0, last_error: null },
    { id: "notify", kind: "notification", label: "Notify billing channel", system: "Webhook outbox", status, result: status === "completed" ? "Notification queued" : null, attempts: status === "completed" ? 1 : 0, last_error: null },
  ];
  const ticket = (id, company, customer, status, arr, users) => ({
    id, subject: "Renewal failed — service at risk",
    body: `Our annual renewal failed this morning and the admin console says our workspace may be suspended in 48 hours. We have ${users} people using the service and cannot lose access during month end.`,
    customer_name: customer, company, arr_usd: arr, active_users: users,
    intent: "Failed renewal", priority: "Urgent", sentiment: "Concerned", route: "Billing Ops", confidence: 0.96,
    risk_reason: `${company} has ${users} active users and ${arr.toLocaleString("en-US")} USD ARR. Human approval is required before account changes.`,
    draft: `Hi ${customer.split(" ")[0]} — I checked the renewal issue. Your workspace can remain active while the payment method is updated once the seven-day billing hold below is approved. Your finance administrator can retry the renewal from Billing → Payment methods.`,
    status, sources, actions: actions(status === "resolved" ? "completed" : "pending"),
    created_at: "2026-08-03T10:09:44Z", approved_at: status === "resolved" ? "2026-08-03T10:12:31Z" : null,
  });
  let tickets = [
    ticket("CS-00420F", "Northstar Logistics", "Elena Park", "needs_approval", 52000, 210),
    ticket("CS-885B37", "Acme Logistics", "Olivia Park", "resolved", 48000, 120),
  ];
  const workflow = [
    { id: "intake", name: "New support ticket", kind: "trigger", description: "REST webhook" },
    { id: "classify", name: "Classify & prioritize", kind: "automation", description: "Structured triage" },
    { id: "retrieve", name: "Retrieve policies", kind: "knowledge", description: "Approved support policies" },
    { id: "draft", name: "Draft response", kind: "automation", description: "Policy-grounded draft" },
    { id: "approval", name: "Human approval", kind: "gate", description: "Required for risky actions" },
    { id: "actions", name: "Execute adapters", kind: "action", description: "Billing, CRM and notification outbox" },
  ];
  const clone = (value) => structuredClone(value);
  window.RELAY_BROWSER_API = async (path, options = {}) => {
    await new Promise((resolve) => setTimeout(resolve, 90));
    if (path === "/api/health") return { status: "ok", automation_provider: "browser" };
    if (path === "/api/workflow") return clone(workflow);
    if (path === "/api/tickets") return clone(tickets);
    if (path === "/api/stats") return {
      tickets: tickets.length,
      needs_approval: tickets.filter((item) => item.status === "needs_approval").length,
      resolved: tickets.filter((item) => item.status === "resolved").length,
      automation_provider: "browser",
    };
    const match = path.match(/^\/api\/tickets\/([^/]+)(?:\/(events|approve|retry|decision))?$/);
    if (!match) throw new Error(`Unknown browser-workspace route: ${path}`);
    const item = tickets.find((candidate) => candidate.id === match[1]);
    if (!item) throw new Error("Case not found");
    if (match[2] === "events") return [];
    if (["approve", "retry"].includes(match[2])) {
      item.status = "resolved";
      item.approved_at = new Date().toISOString();
      item.actions = actions("completed");
    }
    if (match[2] === "decision") {
      item.status = "rejected";
      item.actions = actions("blocked");
    }
    return clone(item);
  };
})();

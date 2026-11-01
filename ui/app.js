"use strict";
const $ = (id) => document.getElementById(id);
let conversationId = null;
const EXAMPLES = [
  "J'ai perdu ma carte", "Pourquoi mon paiement est encore en attente ?", "j'ai été débité deux fois au restaurant",
  "mon virement est en attente depuis deux jours", "j'ai une question sur ma carte", "Mon code PIN est 4821, il est bloqué",
  "I forgot my PIN, what can I do?", "donne-moi une recette de tajine",
];
const pct = (x) => (x == null ? "n/a" : (x * 100).toFixed(1).replace(".", ",") + " %");

function bubble(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

function badge(parent, text, cls = "") {
  const b = document.createElement("span");
  b.className = "badge " + cls;
  b.textContent = text;
  parent.appendChild(b);
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  const userDiv = bubble("user", text);
  $("msg").value = "";
  const body = { customer_id: $("customer").value, message: text };
  if (conversationId) body.conversation_id = conversationId;
  if ($("lang").value) body.lang = $("lang").value;
  let r;
  try {
    const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    r = await res.json();
    if (!res.ok) throw new Error(typeof r.detail === "string" ? r.detail : "requête invalide");
  } catch (e) {
    bubble("bot", "Erreur : " + e.message);
    return;
  }
  conversationId = r.conversation_id;
  if (r.pii.count > 0) {
    const m = document.createElement("div");
    m.className = "masked";
    m.textContent = "Enregistré sous forme masquée : " + r.masked_message;
    userDiv.appendChild(m);
  }
  const bot = bubble("bot", r.reply);
  const badges = document.createElement("div");
  badges.className = "badges";
  badge(badges, r.action, "action " + r.action);
  if (r.article) badge(badges, r.article.id);
  if (r.confidence != null) badge(badges, "confiance " + r.confidence.toFixed(2));
  badge(badges, r.lang.toUpperCase());
  badge(badges, r.latency_ms + " ms");
  bot.appendChild(badges);
  if (r.options && r.options.length) {
    const opts = document.createElement("div");
    opts.className = "options";
    r.options.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = o.n + ". " + o.label;
      b.onclick = () => send(r.action === "CONFIRM_ACTION" ? o.label : String(o.n));
      opts.appendChild(b);
    });
    bot.appendChild(opts);
  }
  showDecision(r);
  if (r.case_id) loadCases();
}

function showDecision(r) {
  const rows = [["Action", r.action], ["Raison", r.reason], ["Méthode", r.method], ["Article", r.article ? r.article.id : "—"],
    ["Intention (EN)", r.intent || "—"], ["Confiance", r.confidence == null ? "—" : r.confidence.toFixed(3)],
    ["Données masquées", r.pii.count ? r.pii.types.join(", ") : "aucune"], ["Rédaction", r.generator]];
  $("decision").innerHTML = "";
  rows.forEach(([k, v]) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    $("decision").append(dt, dd);
  });
}

async function loadCases() {
  const res = await fetch("/api/cases?limit=10");
  const data = await res.json();
  const ul = $("cases");
  ul.innerHTML = "";
  if (!data.cases.length) { ul.innerHTML = '<li class="muted">Aucun pour l\'instant.</li>'; return; }
  data.cases.forEach((c) => {
    const li = document.createElement("li");
    li.textContent = `${c.case_id} — ${c.customer_id} — ${c.reason}`;
    ul.appendChild(li);
  });
}

async function init() {
  const cust = await (await fetch("/api/customers")).json();
  cust.customers.forEach((c) => {
    const o = document.createElement("option");
    o.value = c.customer_id; o.textContent = `${c.customer_id} — ${c.display_name}`;
    $("customer").appendChild(o);
  });
  EXAMPLES.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = t; b.onclick = () => send(t);
    $("examples").appendChild(b);
  });
  try {
    const m = await (await fetch("/api/metrics")).json();
    const b = m.banking77_test;
    const rows = [["Intention (test, 77 cl.)", pct(b.intent.accuracy)], ["Article (test)", pct(b.article.accuracy_hybrid)],
      ["Traité auto. (test)", pct(b.article.coverage)], ["Exactitude traitée", pct(b.article.accepted_accuracy)],
      ["FR top-1 (test)", pct(m.french.test.hit1)], ["Scénarios", `${m.scenarios.passed}/${m.scenarios.n}`]];
    $("metrics").innerHTML = "";
    rows.forEach(([k, v]) => {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      $("metrics").append(dt, dd);
    });
  } catch (e) { $("metrics").innerHTML = "<dt>Évaluation non disponible</dt>"; }
  loadCases();
  bubble("bot", "Bonjour ! Je réponds aux questions sur les cartes, paiements, virements, recharges, l'identité et le compte (banque fictive).");
}

$("form").addEventListener("submit", (e) => { e.preventDefault(); send($("msg").value); });
$("reset").addEventListener("click", () => { conversationId = null; $("log").innerHTML = ""; bubble("bot", "Nouvelle conversation."); });
$("customer").addEventListener("change", () => { conversationId = null; });
init();

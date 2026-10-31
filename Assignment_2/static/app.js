const $ = id => document.getElementById(id); const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c])); const QUICK = [{ icon: "₹", title: "Fee balance", desc: "Payments, balance and deadlines", q: "What is my fee balance?" }, { icon: "◇", title: "Scholarships", desc: "Awards, eligibility and status", q: "What is my scholarship status?" }, { icon: "✓", title: "Attendance", desc: "Thresholds and condonation", q: "What is the minimum attendance requirement?" }, { icon: "↗", title: "Course change", desc: "Approvals and deadlines", q: "Who has to approve a course change request?" }, { icon: "!", title: "Payment issue", desc: "Portal failures and escalation", q: "The payment portal failed. What should I do?" }, { icon: "?", title: "Support ticket", desc: "Create a tracked request", q: "Please create a support ticket: my payment portal crashed while paying." }]; let history = [], sessionId = Math.random().toString(36).slice(2, 10), me = {};
function welcome() { const first = (me.name || "Student").split(" ")[0]; $("chat").innerHTML = `<div class="welcome"><p class="kicker">NORTHSTAR STUDENT AI</p><h1>Good to see you, ${esc(first)}.</h1><p>Ask about your student record, policies, fees and support. Choose a service below or type your own question.</p><div class="quick">${QUICK.slice(0, 3).map(x => `<button data-q="${esc(x.q)}"><b>${x.icon} &nbsp;${x.title}</b><span>${x.desc}</span></button>`).join("")}</div></div>`; $("chat").querySelectorAll("[data-q]").forEach(b => b.onclick = () => send(b.dataset.q)) }
function format(t) { try { return marked.parse(t, { breaks: true, gfm: true }) } catch { return esc(t) } } function userMsg(t) { const d = document.createElement("div"); d.className = "msg user"; d.innerHTML = `<div class="bubble"></div>`; d.querySelector(".bubble").textContent = t; $("chat").appendChild(d); scroll() } function botMsg(t, data, err = false) { const d = document.createElement("div"); d.className = "msg"; let extra = ""; if (data?.suggested_questions?.length) extra = `<div class="quick" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-top:12px">${data.suggested_questions.map(q => `<button data-q="${esc(q)}"><b>${esc(q)}</b></button>`).join("")}</div>`; if (data?.pending_approval) extra += `<div class="quick approval" data-ap="${esc(data.pending_approval.approval_id)}" style="grid-template-columns:repeat(2,1fr);margin-top:12px"><button data-decide="approve"><b>✓ Approve change</b><span>${esc(data.pending_approval.field)} → ${esc(data.pending_approval.new_value)}</span></button><button data-decide="reject"><b>✕ Reject</b><span>Keep my record unchanged</span></button></div>`; d.innerHTML = `<div class="botmark">✦</div><div class="bubble">${format(t)}${extra}</div>`; d.querySelectorAll("[data-decide]").forEach(b => b.onclick = () => decide(d.querySelector(".approval"), b.dataset.decide)); if (err) d.querySelector(".bubble").style.borderColor = "#fda4af"; $("chat").appendChild(d); d.querySelectorAll("[data-q]").forEach(b => b.onclick = () => send(b.dataset.q)); scroll() } async function decide(box, choice) { const id = box.dataset.ap; box.querySelectorAll("button").forEach(b => b.disabled = true); try { const r = await fetch(`/api/approvals/${encodeURIComponent(id)}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: choice }) }); const d = await r.json(); if (r.status === 401) return showLogin("Session ended. Sign in again."); const msg = d.message || d.error || "Request failed."; box.remove(); history.push({ role: "assistant", content: msg }); botMsg(msg, null, !r.ok) } catch (e) { box.querySelectorAll("button").forEach(b => b.disabled = false); botMsg("Unable to reach the server.", null, true) } }
function scroll() { $("chat").scrollTop = $("chat").scrollHeight }
async function send(text) { text = (text || "").trim(); if (!text || $("send").disabled) return; if ($("chat").querySelector(".welcome")) $("chat").innerHTML = ""; userMsg(text); $("send").disabled = true; const wait = document.createElement("div"); wait.className = "msg"; wait.innerHTML = '<div class="botmark">✦</div><div class="bubble">Thinking…</div>'; $("chat").appendChild(wait); scroll(); try { const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, history, session_id: sessionId }) }); const d = await r.json(); wait.remove(); if (r.status === 401) return showLogin("Session ended. Sign in again."); if (!r.ok) botMsg(d.error || "Request failed.", null, true); else { history.push({ role: "user", content: text }, { role: "assistant", content: d.answer }); botMsg(d.answer, d, !!d.error) } } catch (e) { wait.remove(); botMsg("Unable to reach the server.", null, true) } $("send").disabled = false; $("msg").focus() }
function showLogin(m = "") { $("appView").classList.add("d-none"); $("loginView").classList.remove("d-none"); $("loginErr").textContent = m } function showApp(id, name) { me = { id, name: name || id }; $("userName").textContent = me.name; $("userId").textContent = id; $("userAvatar").textContent = me.name.split(/\s+/).map(x => x[0]).slice(0, 2).join(""); $("loginView").classList.add("d-none"); $("appView").classList.remove("d-none"); history = []; welcome(); renderServices() }
function renderServices() { $("serviceGrid").innerHTML = QUICK.map(x => `<button class="service-card" data-q="${esc(x.q)}"><i>${x.icon}</i><h3>${x.title}</h3><p>${x.desc}</p></button>`).join(""); $("serviceGrid").querySelectorAll("[data-q]").forEach(b => b.onclick = () => { switchView("assistant"); send(b.dataset.q) }) } function switchView(v) { document.querySelectorAll(".view").forEach(x => x.classList.add("d-none")); $(v + "View").classList.remove("d-none"); document.querySelectorAll(".nav[data-view]").forEach(n => n.classList.toggle("active", n.dataset.view === v)); const map = { assistant: ["STUDENT ASSISTANT", "Ask Northstar"], services: ["STUDENT SERVICES", "Explore services"], support: ["SUPPORT", "Help centre"] }; $("viewLabel").textContent = map[v][0]; $("viewTitle").textContent = map[v][1]; $("sidebar").classList.remove("open"); $("overlay").classList.remove("active") }
$("loginForm").onsubmit = async e => { e.preventDefault(); const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ student_id: $("sid").value, password: $("pw").value }) }); const d = await r.json(); r.ok ? showApp(d.student, d.name) : $("loginErr").textContent = d.error }; document.querySelectorAll(".demo-row").forEach(b => b.onclick = async () => { const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ student_id: b.dataset.id, password: b.dataset.pw }) }); const d = await r.json(); r.ok ? showApp(d.student, d.name) : $("loginErr").textContent = d.error }); $("form").onsubmit = e => { e.preventDefault(); const t = $("msg").value; $("msg").value = ""; send(t) }; $("logout").onclick = async () => { await fetch("/api/logout", { method: "POST" }); showLogin() }; $("collapse").onclick = () => $("sidebar").classList.toggle("collapsed"); $("menu").onclick = () => { $("sidebar").classList.add("open"); $("overlay").classList.add("active") }; $("overlay").onclick = () => { $("sidebar").classList.remove("open"); $("overlay").classList.remove("active") }; document.querySelectorAll(".nav[data-view]").forEach(n => n.onclick = () => switchView(n.dataset.view)); document.querySelectorAll("[data-question]").forEach(b => b.onclick = () => { switchView("assistant"); send(b.dataset.question) }); (async () => { const m = await (await fetch("/api/me")).json(); m.student ? showApp(m.student, m.name) : showLogin() })();



const demoStudents = [
    {
        id: "S101",
        password: "aarav@123",
        initials: "AP",
        cls: "blue",
        name: "Aarav Patel",
        status: "Merit Scholar · Fully Paid"
    },
    {
        id: "S102",
        password: "priyansh@123",
        initials: "PS",
        cls: "gold",
        name: "Priyansh Shah",
        status: "Partially Paid"
    },
    {
        id: "S103",
        password: "neel@123",
        initials: "NP",
        cls: "red",
        name: "Neel Patel",
        status: "Payment Pending"
    },
    {
        id: "S104",
        password: "riya@123",
        initials: "RM",
        cls: "blue",
        name: "Riya Mehta",
        status: "Scholarship Approved"
    },
    {
        id: "S105",
        password: "yash@123",
        initials: "YD",
        cls: "gold",
        name: "Yash Desai",
        status: "Scholarship Under Review"
    }
];

const PAGE_SIZE = 3;
let currentPage = 0;

function renderDemoStudents() {
    const container = document.getElementById("demoContainer");

    const start = currentPage * PAGE_SIZE;
    const visibleStudents = demoStudents.slice(start, start + PAGE_SIZE);

    container.innerHTML = visibleStudents.map(student => `
        <button class="demo-row"
            data-id="${student.id}"
            data-pw="${student.password}">
            
            <i class="av ${student.cls}">
                ${student.initials}
            </i>

            <span>
                <b>${student.name}</b>
                <small>${student.status}</small>
            </span>

            <em>→</em>
        </button>
    `).join('');

    container.querySelectorAll('.demo-row').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('sid').value = btn.dataset.id;
            document.getElementById('pw').value = btn.dataset.pw;
        });
    });

    document.getElementById("prevStudents").disabled = currentPage === 0;

    document.getElementById("nextStudents").disabled =
        (currentPage + 1) * PAGE_SIZE >= demoStudents.length;
}

document.getElementById("nextStudents").addEventListener("click", () => {
    if ((currentPage + 1) * PAGE_SIZE < demoStudents.length) {
        currentPage++;
        renderDemoStudents();
    }
});

document.getElementById("prevStudents").addEventListener("click", () => {
    if (currentPage > 0) {
        currentPage--;
        renderDemoStudents();
    }
});

renderDemoStudents();
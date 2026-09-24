"""NoticeLens AI: an autonomous lease auditor and tenant defense workspace."""

import json
import html
import os
import re
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

load_dotenv()

st.set_page_config(
    page_title="NoticeLens AI | LexHack 2026",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEMO_TEXT = """3-DAY UNLAWFUL EVICTION NOTICE

To: Jordan Lee, Tenant
Property: 1847 Cedar Avenue, Unit 3B
Date: September 18, 2026

You are hereby ordered to vacate and surrender possession of the premises within three (3) days of delivery of this notice. If you remain after the three-day period, management will change the locks, remove your belongings to the curb, and disable your building access without further notice.

You owe $1,350 in alleged rent and administrative charges. A daily penalty of $450 will be added for every day you remain in the apartment after the deadline. Your security deposit will be retained to cover these charges. No court hearing will be provided because your lease permits immediate termination for any late payment.

Pay the full amount in cash at the management office by 5:00 p.m. tomorrow or surrender your keys. Failure to comply will result in police notification and a report to your employer.

Property Manager: Northstar Residential LLC
Contact: (555) 019-4482 | notices@northstar.example
"""

SYSTEM_PROMPT = """You are NoticeLens AI, a careful civic-tech legal information assistant. Audit the supplied housing notice for procedural and substantive tenant risks. Do not invent a jurisdiction; label jurisdiction-dependent conclusions and recommend local legal aid. Return ONLY valid JSON with this exact shape:
{
  "document_summary": "string",
  "persona_risk_level": "Critical|Moderate|Low",
  "jurisdiction_note": "string",
  "statutory_audit": [{"clause_text":"string","statute_violated":"string","severity":"Critical|High|Moderate|Low","plain_language_explanation":"string"}],
  "defense_action_plan": ["string"],
  "formal_legal_dispute_letter": "string"
}
Use plain language, quote only short relevant excerpts, separate likely violations from issues that require local law review, and never claim to be a lawyer."""

JURISDICTIONS = {
    "General U.S. guidance": {
        "note": "Rules vary by state and city. Confirm deadlines with a local court, legal-aid office, or tenant organization.",
        "resources": [("HUD housing resources", "https://www.hud.gov/states")],
    },
    "California": {
        "note": "Use this as issue-spotting only. Confirm the current notice period and court procedure for the property address.",
        "resources": [("California Courts eviction guide", "https://selfhelp.courts.ca.gov/eviction-landlord")],
    },
    "New York": {
        "note": "Use this as issue-spotting only. New York City and other localities may have different protections and procedures.",
        "resources": [("New York Courts housing guide", "https://www.nycourts.gov/courthelp/Homes/eviction.shtml")],
    },
    "Texas": {
        "note": "Use this as issue-spotting only. Confirm the current notice period and court procedure with local legal aid.",
        "resources": [("TexasLawHelp eviction resources", "https://texaslawhelp.org/eviction")],
    },
}

DEFAULT_AUDIT: Dict[str, Any] = {
    "document_summary": "A property manager demands that the tenant leave within three days, threatens a lockout without a court order, and adds a $450-per-day penalty.",
    "persona_risk_level": "Critical",
    "jurisdiction_note": "Eviction timelines and notice rules vary by state and city. The threats described below are high-risk warning signs, not a substitute for advice from local legal aid.",
    "statutory_audit": [
        {
            "clause_text": "vacate ... within three (3) days ... management will change the locks",
            "statute_violated": "Due process / unlawful self-help eviction (jurisdiction-dependent)",
            "severity": "Critical",
            "plain_language_explanation": "A landlord generally cannot remove a tenant, change locks, or shut off access without following the local court process. Do not ignore the notice, but do not move out solely because of this threat.",
        },
        {
            "clause_text": "$450 will be added for every day you remain",
            "statute_violated": "Potentially unconscionable liquidated damages or penalty (jurisdiction-dependent)",
            "severity": "High",
            "plain_language_explanation": "A daily amount designed to punish a tenant rather than estimate an actual loss may be unenforceable. Ask legal aid to review the lease and the claimed balance.",
        },
        {
            "clause_text": "No court hearing will be provided",
            "statute_violated": "Right to notice and opportunity to be heard before eviction (jurisdiction-dependent)",
            "severity": "Critical",
            "plain_language_explanation": "A lease cannot usually erase the legal process required for a residential eviction. The landlord may need to file a case and obtain a judgment before physical removal.",
        },
        {
            "clause_text": "Your security deposit will be retained to cover these charges",
            "statute_violated": "Security-deposit accounting requirements (jurisdiction-dependent)",
            "severity": "Moderate",
            "plain_language_explanation": "Deposit deductions commonly require an itemized statement and deadlines. Keep the deposit issue separate from the immediate eviction threat and request an accounting in writing.",
        },
    ],
    "defense_action_plan": [
        "Preserve the original notice, envelope, emails, texts, lease, rent receipts, and a dated timeline. Photograph the notice and save a copy outside the home.",
        "Contact a local tenant union, courthouse self-help desk, or legal-aid organization today. Ask specifically about an emergency lockout injunction and the response deadline.",
        "Do not consent to a lock change or sign a move-out agreement under pressure. If access is blocked, document it and contact non-emergency authorities or the local housing agency.",
        "Request a written itemization of the alleged balance and continue paying undisputed rent through a traceable method if safe and legally appropriate.",
        "Avoid threatening or confrontational contact. Use the dispute letter as a record-building first response and have local counsel review it before sending.",
    ],
    "formal_legal_dispute_letter": "Subject: Formal Dispute of Eviction Notice and Demand for Lawful Process\n\nDear Northstar Residential LLC,\n\nI am writing to formally dispute the eviction notice dated September 18, 2026, including the three-day deadline, the proposed $450 daily penalty, and any statement that management may change the locks or remove my belongings without a court order.\n\nPlease provide an itemized statement supporting the alleged $1,350 balance, identify the lease provisions relied upon, and confirm in writing that access to the premises and essential services will not be interrupted. I reserve all rights and defenses available under applicable state and local law, including rights related to notice, judicial process, habitability, retaliation, and the handling of any security deposit.\n\nPlease direct further communication about this dispute in writing. I am seeking assistance from local tenant legal services and request that no self-help action be taken while this matter is reviewed.\n\nSincerely,\nJordan Lee\n1847 Cedar Avenue, Unit 3B",
    "source_references": JURISDICTIONS["General U.S. guidance"]["resources"],
}

CLOSE_PANEL = "</div>"
METRIC_TARGET = "Pilot target"
METRIC_WHY = "Why it matters"
LOCAL_RULES = [
    ("lock|change the locks|remove your belongings|shut off access", "Potential self-help eviction / due process concern (jurisdiction-dependent)", "Critical", "A landlord generally must use the local court process before physically removing a tenant or blocking access. Preserve evidence and seek local help quickly."),
    ("no court|without a hearing|without further notice", "Notice and opportunity-to-be-heard concern (jurisdiction-dependent)", "Critical", "Language that removes notice or a hearing is a serious warning sign. Confirm the required process with a local court or legal-aid provider."),
    ("per day|daily penalty|late fee of|penalty", "Potentially excessive fee or penalty (jurisdiction-dependent)", "High", "A charge intended to punish rather than reflect a real cost may be challenged. Ask for the lease basis and an itemized calculation."),
    ("security deposit.*retain|retain.*security deposit|deposit.*charges", "Security-deposit accounting concern (jurisdiction-dependent)", "Moderate", "Deposit deductions commonly require an itemized explanation and a timely accounting. Request both in writing."),
    ("police|employer|report you|criminal", "Potential coercion or retaliation concern (jurisdiction-dependent)", "High", "Threats involving police, employment, or public exposure can be coercive. Save the exact wording and ask local legal aid about protections."),
]


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        :root {
          --bg:#070b14;
          --bg-2:#0d1626;
          --panel: rgba(10, 16, 28, 0.7);
          --panel-strong: rgba(17, 24, 35, 0.9);
          --line: rgba(140, 163, 255, 0.22);
          --ink:#eef6ff;
          --muted:#9fb0c7;
          --cyan:#7ef7ff;
          --blue:#73a9ff;
          --violet:#a47bff;
          --mint:#7ef7c0;
          --amber:#f7cb74;
          --red:#ff7c96;
          --shadow: 0 0 24px rgba(126,247,255,0.2), 0 0 50px rgba(164,123,255,0.12);
        }

        html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
        h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: 0 !important; }

        .stApp {
          background:
            radial-gradient(circle at 10% 20%, rgba(126,247,255,0.18), transparent 20%),
            radial-gradient(circle at 80% 10%, rgba(164,123,255,0.2), transparent 18%),
            radial-gradient(circle at 60% 80%, rgba(126,247,192,0.14), transparent 24%),
            linear-gradient(120deg, var(--bg), var(--bg-2) 45%, #090f1d 100%);
          color: var(--ink);
        }

        .stApp::before {
          content: "";
          position: fixed;
          inset: 0;
          background:
            linear-gradient(120deg, transparent 0%, rgba(126,247,255,0.08) 25%, transparent 38%, rgba(164,123,255,0.1) 60%, transparent 100%);
          animation: drift 18s ease-in-out infinite alternate;
          pointer-events: none;
        }

        @keyframes drift {
          0% { transform: translate3d(-2%, 0, 0) scale(1); }
          100% { transform: translate3d(3%, 2%, 0) scale(1.08); }
        }

        [data-testid="stSidebar"] {
          background: rgba(10, 16, 28, 0.78);
          backdrop-filter: blur(18px);
          border-right: 1px solid var(--line);
          box-shadow: inset 0 0 0 1px rgba(126,247,255,0.06);
        }

        [data-testid="stMetric"] {
          background: rgba(13, 20, 30, 0.8);
          border: 1px solid var(--line);
          box-shadow: var(--shadow);
          padding: 16px;
          border-radius: 18px;
        }
        [data-testid="stMetricLabel"] { color: var(--muted); }

        .hero {
          position: relative;
          padding: 10px 0 30px;
          margin-bottom: 24px;
          border-bottom: 1px solid rgba(126,247,255,0.12);
        }

        .eyebrow {
          color: var(--cyan);
          font-size: .75rem;
          font-weight: 700;
          letter-spacing: .14em;
          text-transform: uppercase;
          text-shadow: 0 0 12px rgba(126,247,255,0.65);
        }

        .hero h1 {
          font-size: clamp(2.2rem, 4vw, 4.4rem);
          line-height: 0.96;
          margin: 12px 0 10px;
          background: linear-gradient(90deg, #eef6ff 0%, #9ae5ff 22%, #d1dcff 52%, #e5d3ff 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          text-shadow: 0 0 30px rgba(126,247,255,0.15);
        }

        .hero p {
          color: var(--muted);
          max-width: 760px;
          font-size: 1.1rem;
          line-height: 1.6;
        }

        .panel {
          background: linear-gradient(180deg, rgba(18, 26, 38, 0.82), rgba(12, 18, 29, 0.9));
          border: 1px solid var(--line);
          border-radius: 20px;
          padding: 18px 20px;
          margin-bottom: 16px;
          backdrop-filter: blur(16px);
          box-shadow: var(--shadow);
        }

        .panel-title {
          color: var(--ink);
          font-family: 'Space Grotesk';
          font-weight: 600;
          font-size: 1.12rem;
          margin-bottom: 12px;
        }

        .risk {
          display:inline-flex;
          align-items:center;
          gap:7px;
          border-radius:999px;
          padding:5px 11px;
          font-weight:700;
          font-size:.8rem;
          letter-spacing: .02em;
          box-shadow: 0 0 0 1px rgba(255,255,255,0.05), 0 0 16px rgba(126,247,255,0.12);
        }

        .risk-critical, .risk-high { color:#ffdfe0; background: rgba(126, 36, 56, 0.8); border:1px solid rgba(255,124,150,0.45); }
        .risk-moderate { color:#fff0c9; background: rgba(82, 64, 25, 0.9); border:1px solid rgba(247,203,116,0.45); }
        .risk-low { color:#d8fff2; background: rgba(18, 64, 52, 0.9); border:1px solid rgba(126,247,192,0.45); }

        .clause {
          border-left: 3px solid var(--amber);
          background: rgba(19, 26, 38, 0.85);
          padding: 14px 16px;
          margin: 10px 0;
          border-radius: 0 12px 12px 0;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
        }
        .clause-critical { border-left-color: var(--red); }
        .clause-low { border-left-color: var(--mint); }
        .quote { color:#eaf7ff; font-style:italic; margin-bottom:8px; }
        .muted { color:var(--muted); font-size:.9rem; }

        .letter {
          white-space: pre-wrap;
          background: linear-gradient(180deg, #f5f1e9, #f3efe7);
          color:#1b2531;
          padding: 26px;
          border-radius: 16px;
          line-height: 1.75;
          font-family: Georgia, serif;
          border: 1px solid rgba(120, 108, 92, 0.2);
          box-shadow: 0 20px 40px rgba(0,0,0,0.18);
        }

        .notice {
          background: rgba(13, 42, 45, 0.9);
          border: 1px solid rgba(126,247,192,0.38);
          padding: 12px 14px;
          border-radius: 12px;
          color:#d8fff2;
          box-shadow: 0 0 18px rgba(126,247,192,0.12);
        }

        div[data-testid="stExpander"] {
          border-color: rgba(126,247,255,0.2);
          background: rgba(17, 24, 36, 0.84);
          border-radius: 14px;
          overflow: hidden;
        }

        .stButton > button, .stDownloadButton > button {
          border-radius: 12px;
          font-weight: 700;
          background: linear-gradient(135deg, rgba(126,247,255,0.2), rgba(164,123,255,0.18));
          border: 1px solid rgba(126,247,255,0.3);
          color: var(--ink);
          box-shadow: 0 0 18px rgba(126,247,255,0.12);
        }

        .stButton > button:hover, .stDownloadButton > button:hover {
          border-color: rgba(126,247,255,0.5);
          box-shadow: 0 0 20px rgba(126,247,255,0.22);
        }

        textarea, input, select {
          background: rgba(13, 20, 30, 0.8) !important;
          border: 1px solid rgba(126,247,255,0.18) !important;
          border-radius: 12px !important;
          color: var(--ink) !important;
        }

        .stDataFrame, .stDataFrame > div {
          border-radius: 16px;
          overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sanitize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(uploaded_file: Any) -> str:
    try:
        reader = PdfReader(uploaded_file)
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = sanitize_text("\n\n".join(pages))
        if not text:
            raise ValueError("The PDF contains no selectable text. Try an OCR-enabled PDF.")
        return text
    except Exception as exc:
        raise ValueError(f"Could not parse this PDF: {exc}") from exc


def normalize_audit(raw: Dict[str, Any]) -> Dict[str, Any]:
    audit = dict(DEFAULT_AUDIT)
    audit.update({key: value for key, value in raw.items() if value is not None})
    if audit.get("persona_risk_level") not in {"Critical", "Moderate", "Low"}:
        audit["persona_risk_level"] = "Moderate"
    audit["statutory_audit"] = [item for item in audit.get("statutory_audit", []) if isinstance(item, dict)]
    audit["defense_action_plan"] = [str(item) for item in audit.get("defense_action_plan", [])]
    return audit


def run_local_audit(document_text: str, jurisdiction: str) -> Dict[str, Any]:
    findings = []
    lowered_text = document_text.lower()
    for pattern, statute, severity, explanation in LOCAL_RULES:
        match = re.search(pattern, lowered_text)
        if not match:
            continue
        start = max(0, match.start() - 90)
        end = min(len(document_text), match.end() + 130)
        excerpt = re.sub(r"\s+", " ", document_text[start:end]).strip()
        findings.append({"clause_text": excerpt, "statute_violated": statute, "severity": severity, "plain_language_explanation": explanation})
    level = "Low"
    if findings:
        level = "Moderate"
    if any(item["severity"] == "Critical" for item in findings):
        level = "Critical"
    summary = "The document contains language that warrants local tenant-rights review." if findings else "No high-risk pattern was detected by the offline screen. This is not a legal clearance."
    letter = "Subject: Request for Review and Dispute of Housing Notice\n\nDear Property Manager,\n\nI am writing to dispute and request clarification of the attached housing notice. Please provide the specific lease provisions, an itemized accounting of every amount claimed, and confirmation that no lockout, service interruption, or removal will occur except through the lawful process required for this property.\n\nI am preserving the notice and seeking assistance from local tenant legal services. Please communicate further in writing. I reserve all rights and defenses under applicable state and local law.\n\nSincerely,\nTenant"
    return normalize_audit({"document_summary": summary, "persona_risk_level": level, "jurisdiction_note": JURISDICTIONS[jurisdiction]["note"], "statutory_audit": findings, "defense_action_plan": ["Save the original document, delivery evidence, lease, payment records, and a dated timeline.", "Contact local legal aid, a tenant union, or a court self-help desk and ask about the response deadline.", "Do not sign a move-out agreement or surrender keys under pressure before obtaining local advice.", "Request an itemized balance and communicate in writing.", "If access is blocked or essential services are interrupted, document it and seek urgent local assistance."], "formal_legal_dispute_letter": letter, "source_references": JURISDICTIONS[jurisdiction]["resources"]})


def run_live_audit(document_text: str, api_key: str, model: str, jurisdiction: str) -> Dict[str, Any]:
    client = OpenAI(api_key=api_key)
    jurisdiction_context = JURISDICTIONS[jurisdiction]
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Selected jurisdiction: {jurisdiction}. Jurisdiction caution: {jurisdiction_context['note']}\n\nAudit this housing document:\n\n{document_text[:30000]}"},
        ],
    )
    content = response.choices[0].message.content or "{}"
    audit = normalize_audit(json.loads(content))
    audit["source_references"] = jurisdiction_context["resources"]
    return audit


def severity_class(severity: str) -> str:
    value = severity.lower()
    if value in {"critical", "high"}:
        return "risk-critical"
    if value == "moderate":
        return "risk-moderate"
    return "risk-low"


def risk_badge(level: str) -> str:
    icon = {"Critical": "🔴", "Moderate": "🟡", "Low": "🟢"}.get(level, "🟡")
    return f'<span class="risk {severity_class(level)}">{icon} {level} risk</span>'


def render_audit(audit: Dict[str, Any], document_text: str) -> None:
    findings = audit["statutory_audit"]
    critical_count = sum(item.get("severity", "").lower() == "critical" for item in findings)
    st.markdown("### Audit dashboard")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Persona risk", audit["persona_risk_level"])
    metric_cols[1].metric("Flagged clauses", len(findings))
    metric_cols[2].metric("Critical alerts", critical_count)
    metric_cols[3].metric("Action steps", len(audit["defense_action_plan"]))
    if critical_count:
        st.error("Immediate review recommended: preserve the notice and contact local legal aid or a tenant organization today. If access is blocked, document it and seek local emergency help.")

    left, right = st.columns([0.92, 1.08], gap="large")
    with left:
        st.markdown('<div class="panel"><div class="panel-title">Document viewer</div>', unsafe_allow_html=True)
        st.markdown(risk_badge(audit["persona_risk_level"]), unsafe_allow_html=True)
        st.markdown(f"**Summary**  \n{audit['document_summary']}")
        st.markdown(f'<div class="notice">{audit["jurisdiction_note"]}</div>', unsafe_allow_html=True)
        with st.expander("Show extracted document text"):
            st.text_area("Extracted text", document_text, height=300, label_visibility="collapsed")
        st.markdown(CLOSE_PANEL, unsafe_allow_html=True)
        st.markdown('<div class="panel"><div class="panel-title">Trusted starting points</div><div class="muted">These links are orientation resources, not a legal opinion. Verify current rules for the property address.</div>', unsafe_allow_html=True)
        for title, url in audit.get("source_references", []):
            st.markdown(f"- [{html.escape(str(title))}]({html.escape(str(url))})")
        st.markdown(CLOSE_PANEL, unsafe_allow_html=True)
        st.markdown('<div class="panel"><div class="panel-title">Defense action plan</div>', unsafe_allow_html=True)
        for index, step in enumerate(audit["defense_action_plan"], start=1):
            st.markdown(f"**{index:02d}**  {step}")
        st.markdown(CLOSE_PANEL, unsafe_allow_html=True)
    with right:
        st.markdown('<div class="panel"><div class="panel-title">Statutory audit breakdown</div>', unsafe_allow_html=True)
        if not findings:
            st.markdown('<span class="risk risk-low">🟢 No flagged clauses</span>', unsafe_allow_html=True)
        for item in findings:
            severity = item.get("severity", "Moderate")
            clause_class = severity_class(severity)
            clause_text = html.escape(str(item.get("clause_text", "Unspecified clause")))
            statute = html.escape(str(item.get("statute_violated", "Legal review required")))
            explanation = html.escape(str(item.get("plain_language_explanation", "Request local legal review.")))
            st.markdown(
                f'<div class="clause {clause_class}"><span class="risk {clause_class}">{html.escape(severity)}</span>'
                f'<div class="quote">&ldquo;{clause_text}&rdquo;</div><strong>{statute}</strong>'
                f'<div class="muted">{explanation}</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown(CLOSE_PANEL, unsafe_allow_html=True)
        st.markdown('<div class="panel"><div class="panel-title">Formal defense letter</div>', unsafe_allow_html=True)
        letter = audit["formal_legal_dispute_letter"]
        st.markdown(f'<div class="letter">{html.escape(str(letter))}</div>', unsafe_allow_html=True)
        st.download_button("Download defense letter (.md)", f"# NoticeLens Defense Letter\n\n{letter}", file_name="noticelens-defense-letter.md", mime="text/markdown", use_container_width=True)
        packet = json.dumps({"document_summary": audit["document_summary"], "risk_level": audit["persona_risk_level"], "findings": findings, "action_plan": audit["defense_action_plan"], "source_references": audit.get("source_references", [])}, indent=2)
        st.download_button("Export evidence packet (.json)", packet, file_name="noticelens-evidence-packet.json", mime="application/json", use_container_width=True)
        st.markdown(CLOSE_PANEL, unsafe_allow_html=True)


def render_fellowship_section() -> None:
    with st.expander("📜 LexHack 2026 Submission & Fellowship Roadmap", expanded=True):
        st.markdown("### Built for access to justice")
        st.markdown("NoticeLens turns a frightening housing notice into a clear, actionable safety net. It helps tenants understand what is happening, what is risky, and what to do next before a deadline is missed.")

        st.markdown("**The user problem**")
        st.markdown("- Tenants are often served notices written in legal language they cannot interpret quickly.\n- Panic and ambiguity create delayed decisions.\n- A single missed deadline can change housing security, finances, or legal leverage.")

        st.markdown("**The product response**")
        architecture = {
            "Ingestion": "Upload a notice or PDF and convert it into clean, searchable text with a clear evidence trail.",
            "Risk mapping": "Highlight possible self-help eviction language, coercive penalties, due-process concerns, and deposit issues.",
            "Plain-English guidance": "Transform dense legal language into clear explanations that a non-lawyer can actually understand.",
            "Action generation": "Create a practical defense plan and a formal response letter with the right urgency and tone.",
            "Trust boundary": "The tool emphasizes local legal review and keeps its role as issue-spotting support rather than legal advice.",
        }
        for name, detail in architecture.items():
            st.markdown(f"**{name}**  \n{detail}")

        st.markdown("**Why judges should care**")
        st.markdown("- Direct civic impact: protects people facing eviction pressure and housing instability.\n- High stakes decision support: helps users act before a harmful deadline.\n- Practical AI use: turns unstructured legal text into immediate legal triage.\n- Clear deployment path: strong fit with legal aid, tenant unions, and housing nonprofits.")

        st.markdown("**Impact scorecard for the Builders Fellowship**")
        st.dataframe(
            [
                {"Metric": "Time to first useful action", METRIC_TARGET: "Under 5 minutes", METRIC_WHY: "Prevents panic, confusion, and missed deadlines"},
                {"Metric": "Notices triaged", METRIC_TARGET: "500 in 90 days", METRIC_WHY: "Expands legal-aid and tenant-support capacity"},
                {"Metric": "Human-reviewed referrals", METRIC_TARGET: "90% of Critical cases", METRIC_WHY: "Keeps high-risk actions tied to local help"},
            ],
            hide_index=True,
            use_container_width=True,
        )

        st.markdown("**Expansion plan:** add state-specific rule packs, multilingual tenant support, OCR for photographed notices, referral links to local legal aid, and a deployment-ready workflow for housing nonprofits and community clinics.")
        st.caption("Prototype boundary: NoticeLens provides legal information and issue spotting, not legal representation. Local legal-aid review remains the recommended next step.")


def get_source_text(demo_mode: bool, upload: Any) -> Any:
    if demo_mode:
        st.info("Demo fixture loaded: 3-Day Unlawful Eviction Notice with $450/day Penalty")
        return DEMO_TEXT
    if upload:
        try:
            return extract_pdf_text(upload)
        except ValueError as exc:
            st.error(str(exc))
            return None
    st.markdown('<div class="panel"><div class="panel-title">Start with a notice</div><div class="muted">Upload a PDF or switch on One-Click Demo Mode. No API key is needed for the demo.</div></div>', unsafe_allow_html=True)
    return None


def create_audit(source_text: str, api_key: str, model: str, jurisdiction: str, demo_mode: bool) -> Any:
    with st.spinner("Reading the notice and building a tenant-first response..."):
        if not api_key.strip():
            if not demo_mode:
                st.success("Offline audit complete. Add an API key for deeper OpenAI analysis.")
                return run_local_audit(source_text, jurisdiction)
            st.success("Demo audit complete. Add an API key in the sidebar to analyze your own document with OpenAI.")
            audit = normalize_audit(DEFAULT_AUDIT)
            audit["source_references"] = JURISDICTIONS[jurisdiction]["resources"]
            audit["jurisdiction_note"] = JURISDICTIONS[jurisdiction]["note"]
            return audit
        try:
            audit = run_live_audit(source_text, api_key.strip(), model, jurisdiction)
            st.success(f"Live audit complete with {model}.")
            return audit
        except json.JSONDecodeError:
            st.error("The model returned an unreadable audit. Remove the API key to use the built-in demo audit.")
        except Exception as exc:
            st.error(f"Live audit could not be completed: {exc}")
    return None


def main() -> None:
    inject_css()
    with st.sidebar:
        st.markdown("## <div style='display:flex; align-items:center; gap:10px;'><span style='font-size:1.5rem;'>🔎</span><span>NoticeLens AI</span></div>", unsafe_allow_html=True)
        st.caption("LexHack 2026 · Access to Justice & Civic Tech")
        st.divider()
        api_key = st.text_input("OpenAI API key", value=os.getenv("OPENAI_API_KEY", ""), type="password", help="Optional. Leave blank to use the built-in demo audit.")
        model = st.selectbox("Audit model", ["gpt-4o-mini", "gpt-4o"], index=0)
        jurisdiction = st.selectbox("Legal context", list(JURISDICTIONS), help="Sets the legal-aid starting points and tells the model which jurisdiction to consider. Always verify current local law.")
        demo_mode = st.toggle("One-Click Demo Mode", value=True)
        st.divider()
        st.caption("Your document is processed for this session. Check local legal-aid guidance before acting on any result.")

    st.markdown('''
    <div class="hero">
        <div class="eyebrow">Autonomous lease auditor · tenant defense platform</div>
        <h1>Know your rights before the deadline.</h1>
        <p>NoticeLens AI reads threatening housing notices, flags the risky clauses in plain English, and turns confusion into an evidence-backed defense plan in minutes.</p>
        <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:18px;">
            <span class="risk risk-low" style="padding:8px 12px;">⚖️ Built for tenants & housing counselors</span>
            <span class="risk risk-moderate" style="padding:8px 12px;">🧠 AI + civic tech</span>
            <span class="risk risk-critical" style="padding:8px 12px;">🚨 Legal urgency</span>
        </div>
    </div>
    ''', unsafe_allow_html=True)

    st.markdown("""
    <div class="panel">
      <div class="panel-title">Why this matters</div>
      <div class="muted">When tenants receive a dense or threatening notice, they often act too late. Our tool helps them understand the problem quickly, protect their evidence, and take the right next step before a deadline is missed.</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown("**🚀 Fast triage**\nInstantly reads a notice and surfaces the most urgent legal risks.")
    col2.markdown("**📝 Plain language**\nExplains what the clause means without legal jargon or fear-based confusion.")
    col3.markdown("**🛡️ Action plan**\nCreates a defense checklist and a formal response template in one click.")
    col4.markdown("**📦 Evidence export**\nPackages findings into an easy-to-share record for legal aid or future review.")

    upload = st.file_uploader("Upload a housing notice or lease PDF", type=["pdf"], help="Text-based PDFs work best. Use Demo Mode to explore the full workflow instantly.")
    source_text = get_source_text(demo_mode, upload)
    if not source_text:
        render_fellowship_section()
        return

    if demo_mode and "audit" not in st.session_state:
        demo_audit = normalize_audit(DEFAULT_AUDIT)
        demo_audit["source_references"] = JURISDICTIONS[jurisdiction]["resources"]
        demo_audit["jurisdiction_note"] = JURISDICTIONS[jurisdiction]["note"]
        st.session_state["audit"] = demo_audit
        st.session_state["source_text"] = source_text
        st.success("One-click demo audit ready. Explore the risk map and defense letter below.")

    if st.button("Run autonomous audit", type="primary", use_container_width=True):
        audit = create_audit(source_text, api_key, model, jurisdiction, demo_mode)
        if audit:
            st.session_state["audit"] = audit
            st.session_state["source_text"] = source_text

    if "audit" in st.session_state:
        render_audit(st.session_state["audit"], st.session_state["source_text"])
    render_fellowship_section()


if __name__ == "__main__":
    main()
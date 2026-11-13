# 🏛️ Chatbot Enabled Smart Village Service Portal

An AI-assisted, centralized e-governance web portal designed to streamline civic grievance redressal and statutory civil certificate requests for rural citizens.

---

## 📌 Project Overview

In rural governance, citizens frequently face operational friction when reporting civic infrastructure issues or applying for vital certificates due to procedural ambiguity, reliance on intermediaries, and the burden of repeated physical visits to local Panchayat offices.

The **Chatbot Enabled Smart Village Service Portal** bridges this gap by providing a transparent, mobile-friendly digital platform where villagers can register public utility grievances, apply for birth and death certificates, and track application lifecycles in real time. It features a dual-tier **Hybrid AI Chatbot** offering instant procedural answers alongside colloquial **Tanglish** conversational assistance, backed by a centralized supervisory dashboard for village administrative officers to audit documents and update request statuses.

**Operational Jurisdiction:** Tirunelveli District (3 Taluks: Palayamkottai, Tirunelveli, Ambasamudram | 4 Village Panchayats: High Ground, Melapalayam Rural, Reddiarpatti, Munnirpallam).

---

## 🚀 Key Features

* **Civic Grievance Redressal:** Enables residents to report localized utility failures (Drinking Water, Streetlights, Roads, Sanitation/Drainage) with specific physical landmarks and photographic evidence, automatically generating unique tracking reference IDs (e.g., `CMP1001`).
* **Civil Registration Services (Birth & Death Certificates):** Collects vital demographic records alongside uploaded hospital discharge slips or institutional medical reports (Form 4A), incorporating background verification workflows enforcing the statutory 21-day reporting timeframe.
* **Hybrid AI Conversational Assistant:**
  * **Tier 1 (Instant Local Dataset):** Evaluates queries against a 200-question verified procedural benchmark dataset (`dataset/questions.csv`) using sequence similarity matching ($\ge 90\%$ threshold) for zero-latency, zero-cost answers.
  * **Tier 2 (Cloud LLM Fallback):** Routes complex, misspelled, or colloquial **Tanglish** inquiries through the OpenRouter API to **Google Gemma 2 (9B Instruct)** for context-aware guidance, with graceful offline fallback handling.
* **Real-Time Citizen Tracking Dashboard:** Live status monitoring across all submitted complaints and certificate requests (*Pending*, *In Review*, *Approved / Resolved*).
* **Role-Based Administrative Dashboard:** Unified supervisory control panel for Panchayat officers to filter requests by jurisdiction, inspect uploaded evidentiary proofs, and update application statuses.
* **Data & Session Security:** Cryptographic password hashing (`Werkzeug`), session-based route protection, and filesystem-backed media storage with lightweight database path references.

---

## 🛠️ Tech Stack

| Layer | Technology / Tool |
| :--- | :--- |
| **Backend Framework** | Python 3, Flask |
| **Database** | MySQL (Relational Schema with Foreign-Key Referential Integrity) |
| **AI & NLP** | Google Gemma 2 9B (via OpenRouter API), Sequence Similarity Matching |
| **Frontend** | HTML5, CSS3, JavaScript (Fetch API), Jinja2 Templating |
| **Security & Utilities** | Werkzeug (Password Hashing), Python `requests`, `os` environment variables |
| **Local Environment** | XAMPP (Apache & MySQL), Windows PowerShell |

---
---


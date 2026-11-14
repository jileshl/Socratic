# School Collaboration Request & Teacher Research Protocol
**IIT-Bombay Agentic AI Capstone Project: Socratic Tutor (Project #3)**

---

# PART 1: Formal Letter of Request to the Principal

**Date:** 25 October 2026  
**To:**  
The Principal,  
Narayana e-Techno School,  
Borivali, Mumbai, Maharashtra  

**Subject:** Request for Academic Collaboration: Class 10 Science Faculty & Student Testing for IIT-Bombay Capstone Research

Respected Principal Ma'am / Sir,

I am writing to respectfully request your esteemed institution’s collaboration on an academic research project that I am undertaking as part of the **Executive Post Graduate Program in Agentic AI at IIT Bombay**.

Our capstone project, titled **"Socratic Tutor: An NCERT AI Tutor that Teaches, Not Tells"**, aims to solve a critical limitation of current AI chatbots in school education. Most existing AI chatbots act as "answer-dispensing engines" that directly solve students' homework questions, inadvertently short-circuiting their learning process. In contrast, our team is developing an intelligent pedagogical agent designed specifically for **Class 10 CBSE/NCERT Science** that identifies a student’s conceptual misunderstanding, provides progressive Socratic hints grounded in the textbook, checks their mathematical derivations using code, and never gives away the final answer during practice.

To ensure our AI system adheres strictly to authentic classroom pedagogy and CBSE board standards, we seek guidance from an experienced **Class 10 Science (Physics) Teacher** from Narayana School.

### Scope of Teacher Engagement
We are requesting the support of one Class 10 Science teacher for a total of **approximately 3 to 4 hours spread over 2 weeks**:
1. **Initial Pedagogical Consultation (approx. 45–60 mins):** Reviewing our curriculum concept map and validating 8–12 common student misconceptions across Chapters 9, 10, and 11.
2. **Evaluation & Rubric Calibration (approx. 45–60 mins):** Scoring 20 short, anonymous student response transcripts using standard CBSE board marking rubrics to benchmark our AI evaluation system.
3. **Optional System Testing with 3–5 Students (approx. 45 mins):** If permitted by the school and with appropriate parental consent, having 3 to 5 Class 10 students interact with our prototype for 15 minutes to observe how they respond to Socratic hints.

### Data Privacy & Safety Guarantees
* **Strict Minor Privacy:** Our platform enforces complete anonymity. No student names, roll numbers, or personal identifying information are recorded, stored, or processed.
* **Child Safety & Ethical Guardrails:** The platform features specialized guardrails filtering out inappropriate content and immediately flags any signs of student distress.
* **Non-Commercial Academic Use:** This project is strictly academic, non-commercial research under the supervision of IIT Bombay faculty.
* **Institutional Attribution:** We will gladly acknowledge the invaluable pedagogical contribution of Narayana School, Borivali, and the participating faculty in our final project report and presentation.

We would be deeply grateful if you could grant permission for this academic collaboration and nominate a Class 10 Science teacher with whom we could connect.

Thanking you in anticipation.

Yours sincerely,  

**Anurag Singh** (Domain & Product Lead)  
Team: Aman, Jilesh, Abhishek, Vidhya  
IIT-Bombay Agentic AI Program  
Project: Socratic Tutor (https://socratic.duckdns.org/)  

---
\pagebreak
---

# PART 2: Chapter Selection & Complexity Assessment

### Proposed Chapters:
1. **Chapter 9: Light – Reflection and Refraction**
2. **Chapter 10: The Human Eye and the Colourful World**
3. **Chapter 11: Electricity**

### Evaluation: Do These Chapters Meet the Required Capstone Complexity?

**Verdict: YES, they provide the IDEAL combination of technical and pedagogical complexity.**

Here is why this trio is far superior to covering random chapters across biology or chemistry:

| Chapter | Technical & Pedagogical Dimension | Why It Matches Capstone Requirements |
| :--- | :--- | :--- |
| **Ch 9: Light – Reflection & Refraction** | **Mathematical Solvers & Sign Conventions** | • Requires deterministic mathematical calculations in Python/SymPy (`math_tools.py`) for Mirror formula ($1/f = 1/v + 1/u$), Lens formula ($1/f = 1/v - 1/u$), and magnification ($m = -v/u = h'/h$).<br>• High misconception density: students routinely bungle the Cartesian sign convention (positive vs. negative $u, v, f$). |
| **Ch 10: The Human Eye & Colourful World** | **Qualitative & Causal Reasoning** | • Tests the LLM Judge and Diagnostician on **descriptive, qualitative physics** (e.g., ray diagrams for myopia/hypermetropia correction, dispersion of light, atmospheric refraction, Tyndall effect).<br>• Evaluates whether the tutor can explain *why* phenomena happen without relying solely on numerical solvers. |
| **Ch 11: Electricity** | **Multi-Variable Circuit Logic & Algebra** | • Combines algebraic equivalence ($V = IR$, $P = VI = I^2R = V^2/R$, $H = I^2Rt$) with network topology (resistors in series vs. parallel).<br>• Solves the classic "rule calculation" requirement: checking whether code calculates electrical power and equivalent resistance within tolerance. |

### Summary of Complexity Coverage:
* **Deterministic Solvers (L7)**: Covered completely by Chapter 9 & Chapter 11.
* **Concept Dependency Graph (L8/L10)**: Prerequisite flow works naturally (e.g., *Laws of Reflection $\rightarrow$ Spherical Mirrors $\rightarrow$ Refraction $\rightarrow$ Lenses $\rightarrow$ Defects of Vision in Human Eye*).
* **Misconception Detection (L11/L12)**: Every CBSE physics teacher has a clear list of mistakes students make in ray optics and electrical circuits.

---
\pagebreak
---

# PART 3: Comprehensive Teacher Questionnaire & Research Tasks

This questionnaire is organized into 5 structured modules corresponding to the technical layers of the AI system.

```
                  Teacher Knowledge Ingestion
                               │
   ┌──────────────┬────────────┴─────────────┬──────────────┐
   ▼              ▼                          ▼              ▼
Module 1       Module 2                   Module 3       Module 4 & 5
Concepts &     Misconception              Socratic       Rubric Calibration (κ)
Prerequisites  Catalogue (8-12 / ch)     Hint Ladders   & Alerts/Approvals
```

---

### Module 1: The Concept Dependency Graph (L8 & L10 Planning)
*Objective: Build the Directed Acyclic Graph (DAG) of ~25 concepts with prerequisite links.*

**Questions for the Teacher:**
1. **Light (Ch 9)**:
   * What is the logical order of sub-topics you teach? (e.g., *Plane reflection $\rightarrow$ Spherical mirror terms ($P, C, F$) $\rightarrow$ Ray rules $\rightarrow$ Mirror formula & signs $\rightarrow$ Refraction & Snell's law $\rightarrow$ Lens formula $\rightarrow$ Power of lens*).
   * If a student cannot solve a numerical problem using the Mirror Formula, what earlier foundational concept is almost always the culprit?
2. **Human Eye (Ch 10)**:
   * Which concepts from Chapter 9 (Lenses/Refraction) are strict prerequisites before teaching Myopia and Hypermetropia?
3. **Electricity (Ch 11)**:
   * What prerequisite concepts must a student master before solving parallel resistor combinations? (e.g., *Current as charge flow $\rightarrow$ Potential difference as work/charge $\rightarrow$ Ohm's Law*).
4. **Remediation Routing**:
   * If a student fails 3 consecutive practice questions on *Resistors in Parallel*, should the AI route them back to *Ohm's Law* or *Series Resistors*?

---

### Module 2: The Misconception Catalogue (L11 Diagnostician & L12 Reflexion)
*Objective: Collect 8–12 documented student misconceptions per chapter.*

**Template for Teacher Interview:**

#### Chapter 9: Light (Target: 8–10 Misconceptions)
| # | Concept | Common Student Error / Wrong Mental Model | What Question (Probe) Exposes It? |
| :--- | :--- | :--- | :--- |
| **1** | Concave Mirror | Believes concave mirrors *always* form inverted images. | *"What happens when you place your face very close to a shaving mirror (inside the focus)?"* |
| **2** | Sign Convention | Treats focal length of concave mirror as positive because it is "real". | *"On which side of the pole (origin) does the focus lie: along $-x$ or $+x$?"* |
| **3** | Ray Inversion | Confuses lateral inversion (left-right) with vertical inversion (upside down). | *"Why does an ambulance write its name backwards, but not upside down?"* |
| **4** | Refraction | Thinks light bends towards the normal in a rarer medium. | *"When light enters water from air, does it speed up or slow down?"* |
| **5** | Convex Mirror | Forgets that convex mirrors *always* form virtual, erect, and diminished images. | *"Can a driver's rear-view mirror ever show an upside-down truck?"* |

*(Ask the teacher to review, validate, and add 4–5 more for Chapter 9).*

#### Chapter 10: Human Eye (Target: 6–8 Misconceptions)
| # | Concept | Common Student Error / Wrong Mental Model | What Question (Probe) Exposes It? |
| :--- | :--- | :--- | :--- |
| **1** | Myopia Correction | Thinks a convex lens is needed for near-sightedness because the image is formed in front of the retina. | *"Do you need to diverge or converge rays so they reach further back onto the retina?"* |
| **2** | Danger Signal Red | Thinks red light travels faster in air than violet light. | *"Do all colors of light have the same speed in vacuum/air? Why does red scatter least?"* |
| **3** | Atmospheric Refraction| Thinks stars twinkle because their nuclear brightness fluctuates. | *"Does a planet twinkle? Why does light from a point source bend through shifting air layers?"* |

*(Ask the teacher to add 3–4 more for Chapter 10).*

#### Chapter 11: Electricity (Target: 8–10 Misconceptions)
| # | Concept | Common Student Error / Wrong Mental Model | What Question (Probe) Exposes It? |
| :--- | :--- | :--- | :--- |
| **1** | Current in Series | Believes the first resistor "uses up" current, so the second resistor receives less. | *"Does an electron get destroyed in a bulb, or is charge conserved in a loop?"* |
| **2** | Potential vs. Current | Confuses voltage (energy per charge) with current (rate of charge flow). | *"If a circuit is open, can there still be potential difference across the battery terminals?"* |
| **3** | Parallel Resistance | Assumes adding another parallel resistor increases the total circuit resistance. | *"If you open a second toll booth lane on a highway, does traffic resistance increase or decrease?"* |
| **4** | Ammeter / Voltmeter | Tries connecting an ammeter in parallel and a voltmeter in series. | *"What happens if an instrument with almost zero resistance is connected across a high voltage source?"* |

*(Ask the teacher to add 4–5 more for Chapter 11).*

---

### Module 3: Socratic Scaffolding & Progressive Hint Ladders
*Objective: Ensure the Tutor Agent guides students through cognitive steps rather than giving away solutions.*

**Questions for the Teacher:**
1. **The Hint Ladder**:
   * When a student asks: *"Sir, where will the image form if $u = -20\text{ cm}$ and $f = -10\text{ cm}$ for a concave mirror?"*, what is your **Level 1 hint**, **Level 2 hint**, and **Level 3 hint**?
   * *Example Level 1*: *"Where is the object located relative to the Center of Curvature ($R = 2f$)?"*
   * *Example Level 2*: *"If the object is at $C$, where does the ray diagram show the reflected rays meeting?"*
   * *Example Level 3*: *"Use $1/f = 1/v + 1/u$. Substitute $f = -10$ and $u = -20$. Solve for $1/v$."*
2. **Breakdown Intervention**:
   * How many hints do you provide before you give an analogous worked example (a problem with different numbers)?

---

### Module 4: Human Rubric Calibration for the LLM Judge (L13 & Cohen's $\kappa$)
*Objective: Calibrate our automated LLM Judge (`gemini-2.5-flash` or `llama-3.3-70b-instruct`) against human teacher judgment.*

**The Task for the Teacher:**
We will present the teacher with **20 anonymized student responses** to conceptual board questions.  
For each response, the teacher scores three dimensions on a **1 to 5 scale**:

1. **Conceptual Accuracy (1–5)**: Is the physics explanation accurate according to NCERT?
2. **Identified Misconception (1–5)**: Did the feedback correctly point out what the student got wrong?
3. **Socratic Guidance (1–5)**: Did the response give an appropriate hint rather than leaking the answer?

*Formula Used for Capstone Report:*
$$\kappa = \frac{p_o - p_e}{1 - p_e}$$
*(We will calculate Cohen's Kappa $\kappa$ between the teacher's 20 scores and our AI Judge to prove system reliability).*

---

### Module 5: Teacher Dashboard, Alerts, and Question Bank Approvals (L14 & L16)
*Objective: Configure the Teacher-in-the-Loop approval gate and alert triggers.*

**Questions for the Teacher:**
1. **Stuck Student Alerts**:
   * At what point should our system notify you? (Default: Student fails a concept $\ge 3$ sessions in a row, or spends $>15$ minutes on one problem). Is that appropriate?
2. **Question Bank Approval Gate**:
   * When our AI generates a new practice question for the class bank, what would cause you to **Reject** or **Edit** it? (e.g., numbers don't divide cleanly, question is out of CBSE syllabus, misleading phrasing).
3. **Distress / Escalation**:
   * What protocol should the AI follow if a student types phrases of extreme academic anxiety (e.g., *"I'm going to fail, I can't do this"* or unrelated distress)?

---
\pagebreak
---

# PART 4: Student Sanity Check Protocol & Parent Consent Note

### Testing Protocol (3 to 5 Students)
* **Duration**: 15 minutes per student.
* **Format**: Supervised interactive session on a school computer or tablet.
* **Activity**:
  1. Student takes a 2-question pre-quiz on Light or Electricity.
  2. Student interacts with the Socratic Tutor on 1 tricky problem where they have a misconception.
  3. Student takes a 2-question post-quiz to measure **learning gain**.
* **Observation Goal**: Measure whether the student was able to self-correct using hints, and note down any prompt wording that caused confusion.

---

### Parental Consent Note (Template)

```
PARENT / GUARDIAN INFORMED CONSENT FORM

Project Title: Socratic AI Tutor: Research on Adaptive Learning in Science
Institution: Indian Institute of Technology Bombay (IIT-B) — Executive Program in Agentic AI
School Partner: Narayana e-Techno School, Borivali

Dear Parent / Guardian,
Your child has been invited to participate in a brief (15-minute) educational research session evaluating an AI-powered Socratic tutoring system developed under the IIT Bombay Agentic AI program.

Key Highlights for Parents:
1. Purely Educational: The system provides step-by-step physics hints based directly on the NCERT Class 10 textbook.
2. Complete Anonymity: No student names, photos, or personal data will be collected, stored, or published.
3. Safe & Supervised: The session will be conducted under the direct supervision of school faculty.
4. Voluntary: Participation is entirely voluntary and does not impact school grades.

Please sign below to indicate your consent:

Student Name: ___________________________   Class & Section: ____________
Parent / Guardian Name: __________________   Contact No: _________________
Signature: _______________________________   Date: _______________________
```

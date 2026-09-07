import { writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const OUT = resolve("docs/absorb-iq-data-journey-tree.svg");
const W = 4200;
const H = 2400;

const colors = {
  ink: "#0f172a",
  muted: "#475569",
  line: "#475569",
  blueFill: "#dbeafe",
  blueStroke: "#2563eb",
  grayFill: "#f1f5f9",
  grayStroke: "#64748b",
  purpleFill: "#f3e8ff",
  purpleStroke: "#7e22ce",
  tealFill: "#ccfbf1",
  tealStroke: "#0f766e",
  orangeFill: "#ffedd5",
  orangeStroke: "#ea580c",
  redFill: "#fee2e2",
  redStroke: "#dc2626",
  yellowFill: "#fef3c7",
  yellowStroke: "#d97706",
  greenFill: "#dcfce7",
  greenStroke: "#16a34a",
  white: "#ffffff",
};

const svg = [];
const labels = [];
const nodes = [];

function esc(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function wrapText(text, maxChars) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function textBlock({ x, y, text, width, size = 28, weight = 500, fill = colors.ink, maxLines = 10, lineHeight = 1.22, anchor = "start" }) {
  const chars = Math.max(8, Math.floor(width / (size * 0.55)));
  const lines = wrapText(text, chars).slice(0, maxLines);
  const tspans = lines.map((line, i) => {
    const dy = i === 0 ? 0 : size * lineHeight;
    return `<tspan x="${x}" dy="${i === 0 ? 0 : dy}">${esc(line)}</tspan>`;
  }).join("");
  return `<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${tspans}</text>`;
}

function node({ id, x, y, w, h, title, body = "", fill, stroke, titleFill = colors.ink, bodyFill = colors.muted, rx = 24, dash = "", strokeWidth = 3, titleSize = 30, bodySize = 23 }) {
  const titleChars = Math.max(8, Math.floor((w - 56) / (titleSize * 0.55)));
  const titleLineCount = wrapText(title, titleChars).slice(0, 2).length;
  const bodyY = y + 42 + Math.max(1, titleLineCount - 1) * titleSize * 1.22 + 28;
  const bodyLines = Math.max(0, Math.floor((y + h - bodyY - 18) / (bodySize * 1.22)));
  nodes.push(`<g id="${id}">
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" ${dash}/>
    ${textBlock({ x: x + 28, y: y + 42, text: title, width: w - 56, size: titleSize, weight: 800, fill: titleFill, maxLines: 2 })}
    ${body && bodyLines > 0 ? textBlock({ x: x + 28, y: bodyY, text: body, width: w - 56, size: bodySize, weight: 500, fill: bodyFill, maxLines: bodyLines }) : ""}
  </g>`);
}

function chip({ x, y, w, h, text, fill, stroke, size = 19, weight = 800 }) {
  return `<g>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="16" fill="${fill}" stroke="${stroke}" stroke-width="2"/>
    ${textBlock({ x: x + w / 2, y: y + h / 2 + size / 3, text, width: w - 16, size, weight, fill: colors.ink, maxLines: 1, anchor: "middle" })}
  </g>`;
}

function layer({ x, y, w, h, title, subtitle }) {
  svg.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="34" fill="#ffffff" stroke="#dbe3ef" stroke-width="2"/>
  <text x="${x + 32}" y="${y + 58}" font-size="34" font-weight="900" fill="${colors.ink}">${esc(title)}</text>
  <text x="${x + 32}" y="${y + 92}" font-size="22" font-weight="600" fill="${colors.muted}">${esc(subtitle)}</text>`);
}

function pathD(points) {
  return points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ");
}

function arrow({ points, label, lx, ly, color = colors.line, dashed = false, width = 3, labelWidth = 260, labelFill = "#ffffff", marker = "arrow" }) {
  const dash = dashed ? 'stroke-dasharray="12 10"' : "";
  svg.push(`<path d="${pathD(points)}" fill="none" stroke="${color}" stroke-width="${width}" ${dash} marker-end="url(#${marker})" stroke-linejoin="round" stroke-linecap="round"/>`);
  if (label) {
    labels.push(labelGroup({ x: lx, y: ly, text: label, width: labelWidth }));
  }
}

function labelGroup({ x, y, text, width = 260 }) {
  const lines = wrapText(text, Math.floor(width / 12)).slice(0, 3);
  const h = 24 + lines.length * 22;
  const tspans = lines.map((line, i) => `<tspan x="${x + width / 2}" dy="${i === 0 ? 0 : 22}">${esc(line)}</tspan>`).join("");
  return `<g>
    <rect x="${x}" y="${y}" width="${width}" height="${h}" rx="14" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    <text x="${x + width / 2}" y="${y + 29}" font-size="18" font-weight="700" fill="${colors.muted}" text-anchor="middle">${tspans}</text>
  </g>`;
}

function motif({ x, y }) {
  const items = [
    ["PLAN", colors.purpleFill, colors.purpleStroke],
    ["RETRIEVE", colors.tealFill, colors.tealStroke],
    ["ANALYZE", colors.purpleFill, colors.purpleStroke],
    ["VERIFY", colors.redFill, colors.redStroke],
    ["CONCLUDE", colors.purpleFill, colors.purpleStroke],
  ];
  const parts = [];
  for (let i = 0; i < items.length; i += 1) {
    parts.push(chip({ x: x + i * 142, y, w: 124, h: 44, text: items[i][0], fill: items[i][1], stroke: items[i][2], size: 17 }));
  }
  const arrowLabels = ["goal", "query", "evidence", "kept facts"];
  for (let i = 0; i < 4; i += 1) {
    const ax = x + i * 142 + 124;
    parts.push(`<path d="M ${ax + 6} ${y + 22} L ${ax + 22} ${y + 22}" fill="none" stroke="${colors.muted}" stroke-width="2.5" marker-end="url(#tinyArrow)"/>`);
    parts.push(`<text x="${ax + 14}" y="${y + 68}" font-size="15" font-weight="700" fill="${colors.muted}" text-anchor="middle">${esc(arrowLabels[i])}</text>`);
  }
  return parts.join("");
}

svg.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs>
  <marker id="arrow" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto" markerUnits="strokeWidth">
    <path d="M 1 1 L 13 7 L 1 13 z" fill="${colors.line}"/>
  </marker>
  <marker id="tealArrow" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto" markerUnits="strokeWidth">
    <path d="M 1 1 L 13 7 L 1 13 z" fill="${colors.tealStroke}"/>
  </marker>
  <marker id="orangeArrow" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto" markerUnits="strokeWidth">
    <path d="M 1 1 L 13 7 L 1 13 z" fill="${colors.orangeStroke}"/>
  </marker>
  <marker id="tinyArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
    <path d="M 1 1 L 7 4 L 1 7 z" fill="${colors.muted}"/>
  </marker>
  <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
    <feDropShadow dx="0" dy="12" stdDeviation="12" flood-color="#0f172a" flood-opacity="0.09"/>
  </filter>
</defs>
<rect width="${W}" height="${H}" fill="#f8fafc"/>
<text x="70" y="82" font-size="50" font-weight="950" fill="${colors.ink}">Absorbd: How Patient Information Becomes a Grounded Nutrition Protocol</text>
<text x="72" y="122" font-size="24" font-weight="600" fill="${colors.muted}">A left to right data journey tree for a 9-agent clinical nutrition reasoning system for IBD patients</text>`);

layer({ x: 60, y: 155, w: 700, h: 2120, title: "INPUTS", subtitle: "Where information enters" });
layer({ x: 790, y: 155, w: 2540, h: 2120, title: "PROCESSING", subtitle: "Where information travels through storage, retrieval, and agents" });
layer({ x: 3360, y: 155, w: 780, h: 2120, title: "OUTPUTS", subtitle: "What comes out and where it appears" });

svg.push(`<g id="legend">
  <rect x="2480" y="48" width="1610" height="78" rx="24" fill="#ffffff" stroke="#dbe3ef"/>
  ${chip({ x: 2510, y: 65, w: 150, h: 38, text: "Human input", fill: colors.blueFill, stroke: colors.blueStroke, size: 15 })}
  ${chip({ x: 2680, y: 65, w: 120, h: 38, text: "Storage", fill: colors.grayFill, stroke: colors.grayStroke, size: 15 })}
  ${chip({ x: 2820, y: 65, w: 118, h: 38, text: "AI agent", fill: colors.purpleFill, stroke: colors.purpleStroke, size: 15 })}
  ${chip({ x: 2960, y: 65, w: 142, h: 38, text: "Retrieval", fill: colors.tealFill, stroke: colors.tealStroke, size: 15 })}
  ${chip({ x: 3125, y: 65, w: 86, h: 38, text: "RED", fill: colors.redFill, stroke: colors.redStroke, size: 15 })}
  ${chip({ x: 3230, y: 65, w: 112, h: 38, text: "YELLOW", fill: colors.yellowFill, stroke: colors.yellowStroke, size: 15 })}
  ${chip({ x: 3360, y: 65, w: 100, h: 38, text: "GREEN", fill: colors.greenFill, stroke: colors.greenStroke, size: 15 })}
  ${chip({ x: 3480, y: 65, w: 112, h: 38, text: "Output", fill: colors.orangeFill, stroke: colors.orangeStroke, size: 15 })}
  <path d="M 3620 84 L 3705 84" stroke="${colors.tealStroke}" stroke-width="4" stroke-dasharray="12 9" marker-end="url(#tealArrow)"/>
  <text x="3724" y="91" font-size="18" font-weight="700" fill="${colors.muted}">retrieval calls</text>
</g>`);

// Input nodes.
node({ id: "doctor-input", x: 100, y: 240, w: 620, h: 175, fill: colors.blueFill, stroke: colors.blueStroke, title: "Doctor input", body: "Creates patient profile: UC, Crohn's, or Celiac, medication list, symptoms to watch, dietary restrictions, clinical notes." });
node({ id: "lab-upload", x: 100, y: 500, w: 620, h: 190, fill: colors.blueFill, stroke: colors.blueStroke, title: "Lab document upload", body: "Doctor or patient uploads lab PDFs across 11 document types." });
node({ id: "daily-journal", x: 100, y: 780, w: 620, h: 190, fill: colors.blueFill, stroke: colors.blueStroke, title: "Patient daily journal", body: "Conversational check-in chat: symptoms, meds taken or missed, food, sleep, stool count, stress, exercise, notes." });
node({ id: "clinical-kb", x: 100, y: 1080, w: 620, h: 250, fill: colors.tealFill, stroke: colors.tealStroke, title: "Clinical knowledge base", body: "Built offline once: 13 NIH ODS nutrient fact sheets, 15 FDA DailyMed drug labels, 14 peer-reviewed IBD correlation studies." });
node({ id: "access-code", x: 100, y: 1445, w: 620, h: 135, fill: colors.blueFill, stroke: colors.blueStroke, title: "Patient access code entry", body: "Links the patient to their doctor-created profile." });

// Storage and preparation.
node({ id: "profile-store", x: 830, y: 250, w: 410, h: 130, fill: colors.grayFill, stroke: colors.grayStroke, title: "SQLite profile", body: "patient_profile fields.", titleSize: 27, bodySize: 21 });
node({ id: "pdfplumber", x: 830, y: 520, w: 210, h: 125, fill: colors.grayFill, stroke: colors.grayStroke, title: "pdfplumber", body: "Extracted text.", titleSize: 24, bodySize: 19 });
node({ id: "llm-labs", x: 1080, y: 520, w: 250, h: 125, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "LLM lab extraction", body: "Candidate values.", titleSize: 24, bodySize: 19 });
node({ id: "doctor-gate", x: 1370, y: 520, w: 255, h: 125, fill: colors.blueFill, stroke: colors.blueStroke, title: "Doctor confirmation gate", body: "Approval required.", titleSize: 24, bodySize: 19 });
node({ id: "lab-store", x: 1665, y: 520, w: 250, h: 125, fill: colors.grayFill, stroke: colors.grayStroke, title: "SQLite labs", body: "lab_values table.", titleSize: 24, bodySize: 19 });
node({ id: "patient-doc-index", x: 1450, y: 675, w: 465, h: 120, fill: colors.tealFill, stroke: colors.tealStroke, title: "Azure AI Search: patient documents", body: "Chunked, embedded document text tagged with the patient's ID." });
node({ id: "journal-store", x: 830, y: 815, w: 430, h: 120, fill: colors.grayFill, stroke: colors.grayStroke, title: "SQLite journal_entries", body: "Daily symptoms, behaviors, adherence, notes." });
node({ id: "offline-chunk", x: 830, y: 1130, w: 250, h: 125, fill: colors.tealFill, stroke: colors.tealStroke, title: "Offline chunking", body: "Clinical source text.", titleSize: 24, bodySize: 19 });
node({ id: "general-lit", x: 1120, y: 1130, w: 420, h: 125, fill: colors.tealFill, stroke: colors.tealStroke, title: "Azure AI Search literature", body: "General sources, no patient tag.", titleSize: 25, bodySize: 20 });
node({ id: "access-link", x: 830, y: 1460, w: 430, h: 100, fill: colors.grayFill, stroke: colors.grayStroke, title: "Profile link", body: "Patient account mapped to profile." });

node({ id: "profile-prep", x: 1320, y: 225, w: 530, h: 240, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Profile Preparation", body: "Merges profile, confirmed labs, latest symptoms, medication normalization, and active inflammation flag from CRP and calprotectin." });

node({ id: "foundry", x: 1985, y: 1410, w: 760, h: 275, fill: colors.tealFill, stroke: colors.tealStroke, title: "Foundry IQ Knowledge Retrieval", body: "Azure AI Search agentic retrieval. Every query blends general clinical literature with that specific patient's uploaded documents using a per-patient filter." });

node({ id: "stats", x: 1320, y: 1770, w: 690, h: 175, fill: "#ecfeff", stroke: "#0891b2", title: "Statistical Correlation Engine", body: "Separate non-LLM branch. Computes lagged Spearman correlations between behaviors and symptoms: stress, missed meds, foods, sleep, exercise." });

// Agent branches.
node({ id: "agent3", x: 1985, y: 260, w: 760, h: 270, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 3: Deficiency Hypothesis", body: "Uses condition, symptoms, and lab values to propose deficiency candidates." });
nodes.push(`<g>${motif({ x: 2015, y: 425 })}</g>`);
node({ id: "agent4", x: 1985, y: 620, w: 760, h: 270, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 4: Medication Interaction", body: "Checks each medication for drug-nutrient depletions after brand-to-generic normalization." });
nodes.push(`<g>${motif({ x: 2015, y: 785 })}</g>`);
node({ id: "agent5", x: 1985, y: 980, w: 760, h: 270, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 5: Dietary Gap", body: "Maps each dietary restriction to likely nutrient gaps and evidence-backed concerns." });
nodes.push(`<g>${motif({ x: 2015, y: 1145 })}</g>`);

node({ id: "agent6", x: 2870, y: 650, w: 405, h: 165, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 6: Synthesis", body: "Deterministic merge. Counts independent pathways converging on each nutrient." });
nodes.push(`<g>
  ${chip({ x: 2900, y: 765, w: 86, h: 36, text: "RED", fill: colors.redFill, stroke: colors.redStroke, size: 14 })}
  ${chip({ x: 2998, y: 765, w: 112, h: 36, text: "YELLOW", fill: colors.yellowFill, stroke: colors.yellowStroke, size: 14 })}
  ${chip({ x: 3122, y: 765, w: 102, h: 36, text: "GREEN", fill: colors.greenFill, stroke: colors.greenStroke, size: 14 })}
</g>`);
node({ id: "agent7", x: 2870, y: 880, w: 405, h: 160, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 7: Protocol", body: "For each RED or YELLOW nutrient, retrieves dosing evidence: dose, form, timing, evidence level." });
node({ id: "agent8", x: 2870, y: 1110, w: 405, h: 165, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 8: Safety", body: "Red-flag escalation, tolerable upper limits, dose caps, and blocks ungrounded recommendations." });
node({ id: "agent9", x: 2870, y: 1350, w: 405, h: 170, fill: colors.purpleFill, stroke: colors.purpleStroke, title: "Agent 9: Doctor Guide", body: "Prioritizes top issues into 3 appointment questions plus patient action items." });

// Callouts.
node({ id: "verify-callout", x: 2825, y: 250, w: 455, h: 210, fill: "#fff7ed", stroke: colors.redStroke, title: "Differentiator 1", body: "Adversarial VERIFY refuses ungrounded claims. Any finding not explicitly supported by cited evidence is dropped before synthesis.", strokeWidth: 4 });
node({ id: "foundry-callout", x: 2795, y: 1600, w: 500, h: 190, fill: "#f0fdfa", stroke: colors.tealStroke, title: "Differentiator 2", body: "Foundry IQ blends two sources in every query: general clinical literature and patient-uploaded documents filtered by patient ID.", strokeWidth: 4 });

// Output nodes.
node({ id: "trace-output", x: 3400, y: 245, w: 690, h: 130, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Live streaming reasoning trace", body: "Every agent step visible in real time in the UI." });
node({ id: "escalation-output", x: 3400, y: 455, w: 690, h: 125, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Urgent escalation banner", body: "Appears if red-flag symptoms are detected." });
node({ id: "protocol-output", x: 3400, y: 665, w: 690, h: 185, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Prioritized supplement protocol cards", body: "RED, YELLOW, GREEN cards with dose, form, timing, cautions, and citations linked to knowledge sources." });
node({ id: "doctor-questions-output", x: 3400, y: 930, w: 690, h: 145, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Doctor-visit questions and action list", body: "3 tailored questions for the next appointment plus patient action items." });
node({ id: "doctor-dashboard-output", x: 3400, y: 1160, w: 690, h: 185, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Doctor dashboard", body: "Correlation insights card, lab table, journal history, adherence stats." });
node({ id: "patient-app-output", x: 3400, y: 1430, w: 690, h: 185, fill: colors.orangeFill, stroke: colors.orangeStroke, title: "Patient app", body: "Daily nudges, trend panel, doctor visit summary." });

// Main entry and storage arrows.
arrow({ points: [[720, 318], [830, 318]], label: "profile fields: condition, medications, restrictions, notes", lx: 750, ly: 395, labelWidth: 320 });
arrow({ points: [[720, 595], [830, 595]], label: "uploaded lab PDFs, 11 document types", lx: 735, ly: 700, labelWidth: 300 });
arrow({ points: [[1040, 568], [1080, 568]], label: "raw extracted text", lx: 980, ly: 445, labelWidth: 170 });
arrow({ points: [[1330, 568], [1370, 568]], label: "candidate lab values", lx: 1325, ly: 445, labelWidth: 190 });
arrow({ points: [[1625, 568], [1665, 568]], label: "doctor-approved lab values only", lx: 1608, ly: 445, labelWidth: 250 });
arrow({ points: [[1040, 590], [1160, 590], [1160, 735], [1450, 735]], label: "document text chunks for embedding", lx: 1125, ly: 690, labelWidth: 285 });
arrow({ points: [[720, 875], [830, 875]], label: "journal check-in data", lx: 735, ly: 965, labelWidth: 235 });
arrow({ points: [[720, 1205], [830, 1205]], color: colors.tealStroke, marker: "tealArrow", label: "NIH, FDA, and IBD study source text", lx: 735, ly: 1345, labelWidth: 315 });
arrow({ points: [[1080, 1185], [1120, 1185]], color: colors.tealStroke, marker: "tealArrow", label: "embedded clinical chunks", lx: 1085, ly: 1278, labelWidth: 230 });
arrow({ points: [[720, 1512], [830, 1512]], label: "access code and patient identity", lx: 735, ly: 1615, labelWidth: 275 });
arrow({ points: [[1045, 1460], [1045, 355], [1010, 355]], label: "profile linkage", lx: 1085, ly: 395, labelWidth: 185 });

// Profile preparation inputs.
arrow({ points: [[1240, 302], [1320, 302]], label: "doctor-created patient profile", lx: 1055, ly: 165, labelWidth: 260 });
arrow({ points: [[1915, 568], [1940, 568], [1940, 395], [1850, 395]], label: "confirmed lab values", lx: 1865, ly: 445, labelWidth: 210 });
arrow({ points: [[1260, 875], [1290, 875], [1290, 405], [1320, 405]], label: "latest symptoms and adherence", lx: 1055, ly: 705, labelWidth: 245 });
arrow({ points: [[1260, 1510], [1285, 1510], [1285, 445], [1320, 445]], label: "linked patient profile", lx: 1302, ly: 1550, labelWidth: 215 });

// Knowledge source arrows to Foundry.
arrow({ points: [[1540, 1185], [1840, 1185], [1840, 1500], [1985, 1500]], color: colors.tealStroke, marker: "tealArrow", label: "general literature passages", lx: 1595, ly: 1205, labelWidth: 255 });
arrow({ points: [[1915, 735], [1950, 735], [1950, 1470], [1985, 1470]], color: colors.tealStroke, marker: "tealArrow", label: "patient-filtered uploaded document passages", lx: 1640, ly: 820, labelWidth: 300 });

// Profile prep to parallel agents.
arrow({ points: [[1850, 300], [1985, 300]], label: "condition + symptoms + lab values", lx: 1855, ly: 165, labelWidth: 280 });
arrow({ points: [[1850, 345], [1915, 345], [1915, 690], [1985, 690]], label: "normalized medication list", lx: 1810, ly: 510, labelWidth: 250 });
arrow({ points: [[1850, 415], [1895, 415], [1895, 1055], [1985, 1055]], label: "dietary restrictions + profile context", lx: 1660, ly: 900, labelWidth: 300 });

// Agent retrieval calls.
arrow({ points: [[2210, 469], [2210, 1380], [2120, 1380], [2120, 1410]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "deficiency evidence query + patient ID filter", lx: 2225, ly: 910, labelWidth: 300 });
arrow({ points: [[2350, 1410], [2350, 530]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "ranked citations for deficiency findings", lx: 2370, ly: 925, labelWidth: 290 });
arrow({ points: [[2210, 829], [2210, 1385], [2260, 1385], [2260, 1410]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "drug-nutrient query + patient ID filter", lx: 2035, ly: 1055, labelWidth: 285 });
arrow({ points: [[2465, 1410], [2465, 890]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "ranked citations for medication findings", lx: 2485, ly: 1055, labelWidth: 305 });
arrow({ points: [[2210, 1189], [2210, 1388], [2415, 1388], [2415, 1410]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "dietary gap query + patient ID filter", lx: 2038, ly: 1270, labelWidth: 285 });
arrow({ points: [[2580, 1410], [2580, 1250]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "ranked citations for restriction findings", lx: 2600, ly: 1294, labelWidth: 300 });

// Fan-in and sequential agents.
arrow({ points: [[2745, 395], [2810, 395], [2810, 705], [2870, 705]], label: "deficiency candidates + evidence", lx: 2760, ly: 505, labelWidth: 270 });
arrow({ points: [[2745, 755], [2870, 755]], label: "drug-nutrient depletion findings", lx: 2748, ly: 790, labelWidth: 285 });
arrow({ points: [[2745, 1115], [2810, 1115], [2810, 790], [2870, 790]], label: "restriction-driven nutrient gaps", lx: 2760, ly: 960, labelWidth: 285 });
arrow({ points: [[3072, 815], [3072, 880]], label: "RED and YELLOW nutrients", lx: 3090, ly: 822, labelWidth: 230 });
arrow({ points: [[3072, 1040], [3072, 1110]], label: "dosing protocol drafts", lx: 3090, ly: 1050, labelWidth: 220 });
arrow({ points: [[3072, 1275], [3072, 1350]], label: "safe capped recommendations + escalations", lx: 3090, ly: 1288, labelWidth: 305 });

// Agent 7 and 8 retrieval.
arrow({ points: [[2870, 960], [2765, 960], [2765, 1545], [2745, 1545]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "dosing evidence query", lx: 2640, ly: 945, labelWidth: 220 });
arrow({ points: [[2745, 1585], [2850, 1585], [2850, 1000], [2870, 1000]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "dose, form, timing evidence", lx: 2780, ly: 1330, labelWidth: 260 });
arrow({ points: [[2870, 1190], [2785, 1190], [2785, 1620], [2745, 1620]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "upper limit and safety query", lx: 2670, ly: 1180, labelWidth: 265 });
arrow({ points: [[2745, 1650], [2825, 1650], [2825, 1240], [2870, 1240]], color: colors.tealStroke, marker: "tealArrow", dashed: true, label: "ULs, cautions, contraindications", lx: 2838, ly: 1450, labelWidth: 285 });

// Statistical side branch.
arrow({ points: [[1045, 935], [1045, 1855], [1320, 1855]], label: "historical behaviors + symptoms", lx: 1080, ly: 1705, labelWidth: 285 });
arrow({ points: [[2010, 1855], [2830, 1855], [2830, 1440], [2870, 1440]], label: "lagged Spearman observational patterns", lx: 2245, ly: 1795, labelWidth: 320 });

// Callout arrows.
arrow({ points: [[2825, 355], [2700, 355], [2700, 469]], color: colors.redStroke, label: "grounding rule: keep only explicit support", lx: 2688, ly: 250, labelWidth: 315 });
arrow({ points: [[2795, 1685], [2745, 1595]], color: colors.tealStroke, marker: "tealArrow", label: "every retrieval query blends both sources", lx: 2770, ly: 1805, labelWidth: 315 });

// Agent to outputs.
arrow({ points: [[2745, 300], [3340, 300], [3340, 310], [3400, 310]], color: colors.orangeStroke, marker: "orangeArrow", label: "agent step events stream", lx: 2960, ly: 238, labelWidth: 250 });
arrow({ points: [[3275, 1190], [3340, 1190], [3340, 515], [3400, 515]], color: colors.orangeStroke, marker: "orangeArrow", label: "red-flag symptom signal", lx: 3248, ly: 840, labelWidth: 230 });
arrow({ points: [[3275, 985], [3340, 985], [3340, 745], [3400, 745]], color: colors.orangeStroke, marker: "orangeArrow", label: "safe protocol cards + citations", lx: 3260, ly: 900, labelWidth: 270 });
arrow({ points: [[3275, 1435], [3340, 1435], [3340, 1002], [3400, 1002]], color: colors.orangeStroke, marker: "orangeArrow", label: "3 questions + patient actions", lx: 3235, ly: 1360, labelWidth: 260 });
arrow({ points: [[1260, 875], [1290, 875], [1290, 2070], [3340, 2070], [3340, 1252], [3400, 1252]], color: colors.orangeStroke, marker: "orangeArrow", label: "journal history + adherence stats", lx: 2020, ly: 2010, labelWidth: 285 });
arrow({ points: [[1915, 568], [1945, 568], [1945, 2120], [3345, 2120], [3345, 1220], [3400, 1220]], color: colors.orangeStroke, marker: "orangeArrow", label: "lab table values", lx: 2520, ly: 2060, labelWidth: 200 });
arrow({ points: [[2010, 1855], [3330, 1855], [3330, 1252], [3400, 1252]], color: colors.orangeStroke, marker: "orangeArrow", label: "correlation insight card", lx: 3055, ly: 1795, labelWidth: 245 });
arrow({ points: [[2010, 1888], [3355, 1888], [3355, 1492], [3400, 1492]], color: colors.orangeStroke, marker: "orangeArrow", label: "daily nudge triggers + trend data", lx: 2795, ly: 1830, labelWidth: 295 });
arrow({ points: [[3275, 1475], [3400, 1518]], color: colors.orangeStroke, marker: "orangeArrow", label: "doctor visit summary", lx: 3260, ly: 1515, labelWidth: 225 });

svg.push(...nodes);
svg.push(...labels);
svg.push(`<text x="75" y="2305" font-size="20" font-weight="700" fill="${colors.muted}">All arrows are labeled with the data moving across them. Dashed teal arrows represent retrieval calls to Foundry IQ.</text>`);
svg.push("</svg>");

await mkdir(dirname(OUT), { recursive: true });
await writeFile(OUT, svg.join("\n"), "utf8");
console.log(OUT);

// Landing page (M5.3). All dynamic text uses textContent; no HTML parsing.

const SAMPLE_QUESTIONS = [
  "What is the core purpose of the AI Risk Management Framework?",
  "What risks does the Generative AI Profile identify for generative AI?",
  "What are the main components of an adversarial machine learning taxonomy?",
  "How can organizations implement AI governance?",
  "What are the emerging standards for AI transparency?",
  "What are the best practices for AI system monitoring?"
];

const form = document.getElementById("query-form");
const questionBox = document.getElementById("question");
const charCounter = document.getElementById("char-counter");
const askButton = document.getElementById("ask-button");
const sampleContainer = document.getElementById("sample-buttons");
const healthStatus = document.getElementById("health-status");
const resultArea = document.getElementById("result-area");
const answerBox = document.getElementById("answer");
const citationsBox = document.getElementById("citations");
const usageBox = document.getElementById("usage");
const refusalBox = document.getElementById("refusal");
const requestIdBox = document.getElementById("request-id");

const documentTitles = {};

function setText(element, text) {
  element.textContent = text;
}

function showResult() {
  resultArea.classList.remove("hidden");
}

function resetResult() {
  setText(answerBox, "");
  setText(citationsBox, "");
  setText(usageBox, "-");
  setText(refusalBox, "-");
  setText(requestIdBox, "Request ID: -");
}

function renderSamples() {
  for (const [index, question] of SAMPLE_QUESTIONS.entries()) {
    const button = document.createElement("button");
    button.className = "btn";
    button.type = "button";
    button.textContent = `Q${index + 1}: ${question}`;
    button.addEventListener("click", () => {
      questionBox.value = question;
      questionBox.focus();
      updateCounter();
    });
    sampleContainer.appendChild(button);
  }
}

function updateCounter() {
  setText(charCounter, `${questionBox.value.length} / 2000 characters`);
}

async function loadDocumentTitles() {
  try {
    const response = await fetch("/v1/documents");
    if (!response.ok) return;
    const data = await response.json();
    for (const item of data.items || []) {
      documentTitles[item.document_id] = item.filename;
    }
  } catch {
    // Titles are decoration; citations fall back to the document id.
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/healthz");
    setText(healthStatus, response.ok ? "Service is healthy." : `Service returned ${response.status}.`);
  } catch {
    setText(healthStatus, "Could not reach the service.");
  }
}

function renderCitations(citations) {
  if (!citations.length) return;
  const heading = document.createElement("p");
  heading.className = "muted";
  heading.textContent = "Citations:";
  citationsBox.appendChild(heading);
  const list = document.createElement("ul");
  for (const citation of citations) {
    const item = document.createElement("li");
    const title = documentTitles[citation.document_id] || citation.document_id;
    item.textContent = `${title}, page ${citation.page}`;
    list.appendChild(item);
  }
  citationsBox.appendChild(list);
}

function renderUsage(usage) {
  const calls = usage.calls || 0;
  const prompt = usage.prompt_tokens || 0;
  const completion = usage.completion_tokens || 0;
  const seconds = usage.api_seconds || 0;
  setText(
    usageBox,
    `${calls} LLM call${calls === 1 ? "" : "s"} - ${prompt} prompt tokens - ` +
      `${completion} completion tokens - ${seconds} s - cache ${usage.cache || "bypass"}`
  );
}

async function submitQuery(event) {
  event.preventDefault();
  const question = questionBox.value.trim();
  if (!question) return;
  askButton.disabled = true;
  showResult();
  resetResult();
  try {
    const response = await fetch("/v1/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question })
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (response.status === 429) {
      const retryAfter = response.headers.get("Retry-After") || "a few";
      setText(refusalBox, `Rate limited. Retry after ${retryAfter} seconds.`);
      return;
    }
    if (response.status === 503) {
      setText(refusalBox, "The service is unavailable right now. Try again shortly.");
      return;
    }
    if (!response.ok) {
      setText(refusalBox, data.detail || `Request failed (${response.status}).`);
      return;
    }
    setText(requestIdBox, `Request ID: ${data.request_id || "-"}`);
    if (data.refused) {
      setText(answerBox, data.answer || "");
      setText(refusalBox, `No answer: ${data.refusal_reason || "refused"}.`);
      setText(usageBox, "0 LLM calls");
      return;
    }
    setText(answerBox, data.answer || "");
    renderCitations(data.citations || []);
    renderUsage(data.usage || {});
  } catch {
    setText(refusalBox, "Could not reach the service.");
  } finally {
    askButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderSamples();
  updateCounter();
  questionBox.addEventListener("input", updateCounter);
  form.addEventListener("submit", submitQuery);
  checkHealth();
  loadDocumentTitles();
});

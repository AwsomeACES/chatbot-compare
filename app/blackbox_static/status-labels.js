/* One source of status wording for every screen (T-019).
   Loaded before the screen scripts, so simple.js, assurance.js, governance.js and
   calibration.js all read the same words for the same machine state. */
(() => {
  /* The canonical labels. A declaration is never presented as proven, missing evidence is
     never a measured zero, and unknown cost is never shown as zero. */
  const RESULT = {
    passed: "Passed",
    pass: "Passed",
    failed: "Needs attention",
    fail: "Needs attention",
    not_tested: "Not tested",
    exists: "Declaration only",
    queued: "Queued",
    running: "Running",
    stopped: "Stopped",
    interrupted: "Interrupted",
    timed_out: "Timed out",
    completed: "Completed",
    budget_limit: "Stopped at budget limit",
  };

  /* Qualifications that sit beside a result rather than replacing it. */
  const QUALIFIER = {
    estimated: "Estimated",
    low_confidence: "Low confidence",
    needs_review: "Needs review",
    unknown: "Unknown",
    declaration: "Declaration only",
    not_measured: "Not measured",
  };

  const EXPLAIN = {
    not_tested: "Evidence is missing, so nothing was measured. This is not a failed answer.",
    exists: "A control was declared. A declaration does not show that it works.",
    estimated: "Produced by a judge from evidence, not a deterministic rule.",
    low_confidence: "Too few comparable results to rely on this figure.",
    needs_review: "A person should read the evidence before relying on this.",
    unknown: "Usage, price or billing was not reported. Unknown never means zero.",
    not_measured: "No measured value exists for this view; coverage is shown separately.",
  };

  const friendly = (value) => String(value ?? "").replaceAll("_", " ");

  window.StudioStatus = {
    RESULT,
    QUALIFIER,
    EXPLAIN,
    /* A machine status or verdict as words. Unknown values are humanised, never invented. */
    label(value) {
      const key = String(value ?? "").trim();
      return RESULT[key] || QUALIFIER[key] || friendly(key);
    },
    /* The one-line reason behind a qualification, or "" when there is nothing to add. */
    explain(value) {
      return EXPLAIN[String(value ?? "").trim()] || "";
    },
    /* Cost wording: only a known zero may read as zero. */
    cost(microUsd, { noCalls = false } = {}) {
      if (noCalls) return "$0 (no calls)";
      if (microUsd == null) return QUALIFIER.unknown;
      return `$${(microUsd / 1e6).toFixed(6)}`;
    },
    friendly,
  };
})();

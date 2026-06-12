(function () {
  "use strict";
  const data = JSON.parse(document.getElementById("guide-data").textContent);
  const REQ_LABELS = {
    uv_resistant: "UV Resistant", flexible: "Flexible", high_strength: "High Strength",
    heat_resistant: "Heat Resistant", easy_to_print: "Easy to Print",
    budget_friendly: "Budget Friendly", impact_resistant: "Impact Resistant",
  };
  const CAT_RANK = { everyday: 0, engineering: 1, flexible: 2, support: 3 };
  const results = document.getElementById("picker-results");

  function checkedReqs() {
    return Array.from(document.querySelectorAll(".picker-req:checked")).map((c) => c.value);
  }

  function scoreGroup(group, reqs) {
    let best = null;
    for (const sub of group.subtypes) {
      const satisfied = reqs.filter((r) => sub[r]).length;
      const score = reqs.length ? satisfied / reqs.length : 0;
      const isBase = sub.material_type === "" || sub.material_type === "Basic";
      if (!best || score > best.score || (score === best.score && isBase && !best.isBase)) {
        best = { sub, score, isBase };
      }
    }
    return best;
  }

  function chip(label, met) {
    return `<span class="badge ${met ? "bg-success" : "bg-light text-muted"} me-1">${met ? "✓" : "✗"} ${label}</span>`;
  }

  function card(group, best, reqs) {
    const score = best.score;
    let badge = "";
    if (score >= 0.999) badge = '<span class="badge bg-warning text-dark">★ Perfect match</span>';
    else if (score >= 0.5) badge = `<span class="badge bg-info text-dark">${Math.round(score * 100)}% match</span>`;
    const everyday = group.category === "everyday"
      ? '<span class="badge bg-primary me-1">Everyday favorite</span>' : "";
    const surfaced = (!best.isBase && best.sub.material_type)
      ? `<div class="small text-muted">best match: <strong>${group.name} ${best.sub.material_type}</strong></div>` : "";
    const chips = reqs.map((r) => chip(REQ_LABELS[r], best.sub[r])).join("");
    const warns = [];
    if (best.sub.drying_need === "required") {
      const dt = best.sub.dry_temp ? ` ${best.sub.dry_temp}°C` : "";
      const dh = best.sub.dry_time ? `/${best.sub.dry_time}h` : "";
      warns.push(`<span class="badge bg-warning text-dark me-1">⚠ Requires drying${dt}${dh}</span>`);
    } else if (best.sub.drying_need === "recommended") {
      warns.push('<span class="badge bg-light text-muted me-1">Drying recommended</span>');
    }
    if (best.sub.requires_enclosure) warns.push('<span class="badge bg-danger me-1">⚠ Needs enclosure</span>');
    return `<div class="col-md-6 col-lg-4 mb-3"><div class="card h-100"><div class="card-body">
      <div class="d-flex justify-content-between align-items-start">
        <h5 class="card-title mb-1">${group.name}</h5><div>${everyday}${badge}</div></div>
      <p class="card-text small text-muted">${group.description || ""}</p>${surfaced}
      <div class="mb-2">${chips}</div><div>${warns.join("")}</div>
    </div></div></div>`;
  }

  function emptyState() {
    const everyday = data.filter((g) => g.category === "everyday");
    const cards = everyday.map((g) =>
      `<div class="col-md-6 col-lg-3 mb-3"><div class="card h-100 border-primary"><div class="card-body">
        <span class="badge bg-primary mb-1">Everyday favorite</span>
        <h5 class="card-title">${g.name}</h5>
        <p class="card-text small text-muted">${g.description || ""}</p></div></div></div>`
    ).join("");
    results.innerHTML = `<div class="col-12"><p class="text-muted">New to this? Start with one of these four:</p></div>${cards}`;
  }

  function render() {
    const reqs = checkedReqs();
    if (!reqs.length) { emptyState(); return; }
    const showAll = document.getElementById("picker-show-all").checked;
    const scored = data.map((g) => ({ g, best: scoreGroup(g, reqs) }))
      .sort((a, b) => (b.best.score - a.best.score)
        || (CAT_RANK[a.g.category] - CAT_RANK[b.g.category])
        || a.g.name.localeCompare(b.g.name));
    const visible = scored.filter((s) => showAll || s.best.score >= 0.5);
    if (!visible.length) {
      results.innerHTML = '<div class="col-12"><p class="text-muted">No strong matches — tick "Show all materials".</p></div>';
      return;
    }
    results.innerHTML = visible.map((s) => card(s.g, s.best, reqs)).join("");
  }

  document.querySelectorAll(".picker-req").forEach((c) => c.addEventListener("change", render));
  document.getElementById("picker-show-all").addEventListener("change", render);
  document.getElementById("picker-clear").addEventListener("click", function () {
    document.querySelectorAll(".picker-req:checked").forEach((c) => (c.checked = false));
    render();
  });
  render();
})();

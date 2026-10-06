"use strict";
(() => {
  const A = window.MomApp,
    H = window.Assistance,
    E = A.escapeHtml;
  const statuses = {
    queued: "待寄送",
    paused: "通道停用，暫停寄送",
    retry: "等待安全重試",
    dispatching: "處理中",
    accepted: "通道已受理（不代表對方已閱讀）",
    unknown: "結果不明，請核對",
    failed: "發送失敗",
    missed: "已錯過寄送時間",
    cancelled: "已取消",
    paused_after_restore: "還原後暫停",
  };
  function readiness(r) {
    const absent = Object.entries(r.channels)
      .filter(([, ready]) => !ready)
      .map(([channel]) => (channel === "line" ? "員工 LINE" : "Email"));
    return `${absent.length ? `<p class="notice-card warn">${E(absent.join("、"))}：此通道尚未設定；可以先保存停用的提醒。請管理員設定後再啟用。</p>` : ""}<div class="notice-card ${!r.enabled || !r.worker_running || r.restore_pending ? "warn" : ""}">${E(r.restore_pending ? "資料由備份還原，提醒已暫停；管理員核對後，仍須逐項重新啟用。" : !r.enabled ? "自動提醒尚未啟用，目前不會對外發送。" : !r.worker_running ? "提醒排程暫時未運作，請先人工處理期限並通知管理員。" : "提醒排程正在運作。")}<br><span class="muted">Email：${r.channels.email ? "已設定" : "尚未設定"} · 員工 LINE：${r.channels.line ? "已設定" : "尚未設定"}</span></div>`;
  }
  async function open(c, origin = "case") {
    const ctx = H.context();
    if (!ctx) return;
    const recovered = await H.recover(c),
      b = await A.api(`${H.base(c)}/reminders`);
    if (!H.current(ctx)) return;
    const body =
      recovered +
      readiness(b.readiness) +
      '<p class="muted">提醒依現有待辦／工作單期限排程。來源完成、結案或接收同意變更時會取消；提醒不會替您開票、轉帳或判定期限。</p>' +
      b.rules
        .map(
          (r) =>
            `<article class="operation-record"><h3>${r.channel === "line" ? "員工 LINE" : "Email"} · ${r.enabled ? "已啟用" : "已停用"}</h3><p>期限：${E(new Date(r.source_due_at).toLocaleString("zh-TW"))} · 提前 ${r.offset_minutes} 分鐘 · ${r.repeat_hours ? "每日" : "一次"}</p>${r.pause_reason ? `<p class="notice-card warn">需重新核對：${E(r.pause_reason)}</p>` : ""}${H.button("查看內容", "reminder-reveal", c, r.id, `data-origin="${E(origin)}"`)}${!b.case_closed ? H.button("修改／重新啟用", "reminder-form", c, r.id, `data-origin="${E(origin)}"`) : ""}</article>`,
        )
        .join("") +
      "<h3>寄送紀錄</h3>" +
      b.jobs
        .map(
          (j) =>
            `<article class="operation-record"><h3>${E(statuses[j.status] || j.status)}</h3><p>${E(new Date(j.send_at).toLocaleString("zh-TW"))} · ${j.attempt_no} 次處理</p>${["unknown", "failed"].includes(j.status) ? H.button("核對寄送結果", "reminder-job-reconcile", c, j.id, `data-origin="${E(origin)}"`) : ""}<details><summary>處理歷史</summary>${b.attempts
              .filter((a) => a.job_id === j.id)
              .map(
                (a) =>
                  `<p>${E(a.created_at)} · ${E(statuses[a.status] || a.status)} · ${E(a.error_code || a.reference || "")}</p>`,
              )
              .join("")}</details></article>`,
        )
        .join("");
    if (
      A.openSheet(
        "自動提醒與寄送紀錄",
        body,
        true,
        "deadlines",
        c,
        ctx.generation,
      )
    )
      A.setSheetBack(
        () =>
          origin === "tasks"
            ? window.TravelOperations.open(c, "tasks")
            : origin === "alltasks"
              ? A.closeSheet() && A.setView("tasks")
              : origin === "home"
                ? A.closeSheet() && A.setView("today")
                : A.openCase(c),
        origin === "tasks"
          ? "返回期限待辦"
          : origin === "alltasks"
            ? "返回全部待辦"
            : origin === "home"
              ? "返回工作總覽"
              : "返回案件",
      );
  }
  async function form(el) {
    const c = el.dataset.caseId,
      id = el.dataset.id,
      origin = el.dataset.origin || "case",
      ctx = H.context();
    if (!ctx) return;
    const b = await A.api(`${H.base(c)}/operations`),
      r = await A.api("/api/mom/reminder-status"),
      crm = await A.api(`${H.base(c)}/crm`);
    if (b.case.status === "closed")
      throw new Error("案件已結案，提醒僅供查看。");
    const old = id
      ? await A.api(`${H.base(c)}/reminders/${encodeURIComponent(id)}/reveal`, {
          headers: H.headers(ctx.privacy.actor),
        })
      : {};
    const kind = old.source_kind || el.dataset.sourceKind || "work_item",
      sourceId = old.source_id || el.dataset.sourceId;
    const origins =
      kind === "service_order"
        ? b.service_orders.filter(
            (v) =>
              ![
                "completed",
                "declined",
                "withdrawn",
                "supplier_declined",
              ].includes(v.status),
          )
        : b.work_items.filter((v) => v.status === "open");
    if (!origins.length)
      throw new Error("沒有可提醒的未完成期限，請先新增待辦或工作單。");
    const staff = Object.entries(r.staff_recipients).flatMap(
      ([channel, items]) =>
        items.map((address) => [
          `${channel}|staff|${address}`,
          `${channel === "line" ? "員工 LINE" : "員工 Email"} · ${address}`,
        ]),
    );
    const customer = crm.customer;
    if (customer?.consents.email?.granted)
      staff.push(["email|customer|", "目前關聯客戶 Email（已同意）"]);
    const choices = Object.fromEntries(staff);
    if (!staff.length)
      choices["email|staff|"] = "Email（尚未設定，只能保存停用提醒）";
    const selected = `${old.channel || "email"}|${old.recipient_kind || "staff"}|${old.recipient_kind === "customer" ? "" : old.recipient || ""}`;
    const body =
      readiness(r) +
      H.select(
        "提醒來源與期限",
        "source_id",
        Object.fromEntries(
          origins.map((v) => [
            v.id,
            `${v.title} · ${new Date(v.due_at).toLocaleString("zh-TW")}`,
          ]),
        ),
        sourceId,
      ) +
      H.select("接收對象／通道", "destination", choices, selected) +
      A.field(
        "提前幾分鐘",
        "offset_minutes",
        old.offset_minutes ?? 60,
        'type="number" min="0" max="43200" required',
      ) +
      H.select(
        "提醒頻率",
        "repeat_hours",
        { 0: "一次", 24: "每日，直到來源完成" },
        String(old.repeat_hours || 0),
      ) +
      H.text(
        "實際寄送內容（請核對接收人可見資訊）",
        "body",
        old.body || "請核對旅行案件期限與待辦。",
        2000,
      ) +
      H.select(
        "保存狀態",
        "enabled",
        { false: "停用（先保存設定）", true: "啟用自動寄送" },
        String(old.enabled || false),
      ) +
      '<p class="muted">新增、修改或重新啟用後，只處理之後的提醒時段；已錯過的時段不會補寄，請另行人工聯絡。</p>';
    H.mount(
      ctx,
      c,
      "設定期限提醒",
      "reminderForm",
      body,
      {
        scope: c,
        target: id,
        action: "reminder.write",
        endpoint: `${H.base(c)}/reminders${id ? "/" + encodeURIComponent(id) : ""}`,
        method: id ? "PATCH" : "POST",
        revision: old.revision,
        kind,
        origins,
        customer,
        returnAction: "reminder-open",
      },
      () => open(c, origin),
    );
  }
  async function reveal(el) {
    const c = el.dataset.caseId,
      origin = el.dataset.origin || "case",
      ctx = H.context();
    if (!ctx) return;
    const r = await A.api(
      `${H.base(c)}/reminders/${encodeURIComponent(el.dataset.id)}/reveal`,
      { headers: H.headers(ctx.privacy.actor) },
    );
    if (!H.current(ctx)) return;
    if (
      A.openSheet(
        "提醒內容",
        `<div data-private><p>接收對象：${E(r.recipient_kind === "customer" ? "案件客戶 Email" : r.recipient)}</p><p class="preserve-lines">${E(r.body)}</p><p>${r.enabled ? "已啟用" : "已停用"}</p></div>`,
        true,
        "deadlines",
        c,
        ctx.generation,
      )
    )
      A.setSheetBack(() => open(c, origin), "返回提醒");
  }
  async function reconcile(el) {
    const c = el.dataset.caseId,
      origin = el.dataset.origin || "case",
      ctx = H.context();
    if (!ctx) return;
    const b = await A.api(`${H.base(c)}/reminders`),
      job = b.jobs.find((v) => v.id === el.dataset.id);
    if (!job) throw new Error("寄送紀錄不存在。");
    const frozen = await A.api(
      `${H.base(c)}/reminder-jobs/${encodeURIComponent(job.id)}/reveal`,
      { headers: H.headers(ctx.privacy.actor) },
    );
    H.mount(
      ctx,
      c,
      "核對寄送結果",
      "reminderJobForm",
      `<p class="muted">原寄送對象：${E(frozen.recipient || "未建立寄送内容")}<br>Message-ID：${E(frozen.message_id)}</p><p class="preserve-lines">${E(frozen.body || "")}</p><p class="notice-card warn">寄送結果不明或失敗。請先核對寄件紀錄；確認未寄出才重試，重試可能造成重複寄送。</p>` +
        H.select(
          "實際核對結果",
          "decision",
          b.case_closed
            ? { accepted: "已確認通道受理，追加紀錄", cancel: "取消後續寄送" }
            : {
                accepted: "已確認通道受理，追加紀錄",
                retry: "確認未送出，明確要求重試",
                cancel: "取消後續寄送",
              },
        ) +
        '<label class="checkbox-pill"><input type="checkbox" name="duplicate_risk_checked">要求重試時，我已核對可能重複寄送的風險。</label>',
      {
        scope: c,
        target: job.id,
        action: "crm.reminder.confirm",
        endpoint: `${H.base(c)}/reminder-jobs/${encodeURIComponent(job.id)}/confirm`,
        revision: frozen.revision,
        returnAction: "reminder-open",
      },
      () => open(c, origin),
    );
  }
  async function refreshReadiness() {
    try {
      const r = await A.api("/api/mom/reminder-status");
      document.querySelector("#reminderReadiness").innerHTML = readiness(r);
    } catch (err) {
      document.querySelector("#reminderReadiness").textContent =
        "暫時無法確認提醒狀態，請先人工處理期限。";
    }
  }
  A.registerHomeLoader(refreshReadiness);
  window.addEventListener("travel-settings-open", refreshReadiness);
  A.registerAction("reminder-open", (el) =>
    open(el.dataset.caseId, el.dataset.origin || "case"),
  );
  A.registerAction("reminder-form", form);
  A.registerAction("reminder-reveal", reveal);
  A.registerAction("reminder-job-reconcile", reconcile);
  A.registerForm("reminderForm", async (form) => {
    const op = form.assistanceOperation;
    if (form.assistanceCommand?.frozen) {
      await H.submit(form, {}, op);
      await H.saved(form, "已核對上次保存結果。");
      return;
    }
    const v = Object.fromEntries(new FormData(form)),
      source = op.origins.find((o) => o.id === v.source_id),
      [channel, recipient_kind, recipient] = v.destination.split("|"),
      customer = op.customer;
    const data = {
      ...H.evidence(v),
      source_kind: op.kind,
      source_id: source.id,
      source_revision: source.revision,
      channel,
      recipient_kind,
      recipient,
      offset_minutes: Number(v.offset_minutes),
      repeat_hours: Number(v.repeat_hours),
      body: v.body,
      enabled: v.enabled === "true",
      ...(op.target ? { expected_revision: op.revision } : {}),
      ...(recipient_kind === "customer"
        ? {
            customer_id: customer.id,
            customer_revision: customer.revision,
            consent_revision: customer.consents.email.revision,
          }
        : {}),
    };
    await H.submit(form, data, op);
    await H.saved(form, "提醒設定已保存，請核對通道與排程狀態。");
  });
  A.registerForm("reminderJobForm", async (form) => {
    const op = form.assistanceOperation;
    if (form.assistanceCommand?.frozen) {
      await H.submit(form, {}, op);
      await H.saved(form, "已核對上次保存結果。");
      return;
    }
    const v = Object.fromEntries(new FormData(form));
    await H.submit(
      form,
      {
        ...H.evidence(v),
        expected_revision: op.revision,
        decision: v.decision,
        duplicate_risk_checked: v.duplicate_risk_checked === "on",
      },
      op,
    );
    await H.saved(form, "已保存寄送核對結果。");
  });
})();

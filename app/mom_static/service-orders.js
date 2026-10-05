"use strict";
// Manual service desk: supplier actions and cash transfers occur outside this website.
(() => {
  const A = window.MomApp,
    E = A.escapeHtml,
    $ = (s) => document.querySelector(s);
  const kinds = {
    change: "改期／異動",
    cancellation: "取消訂購",
    refund: "退款",
    incident: "旅中事件",
  };
  const states = {
    open: "需求已記錄",
    awaiting_supplier: "等供應商回覆",
    awaiting_customer: "等客人決定",
    approved: "客人已採用",
    processing: "處理中",
    settling: "核對收退款",
    completed: "已完成",
    declined: "客人未採用",
    withdrawn: "需求已撤回",
    supplier_declined: "供應商未能承辦",
  };
  const actions = {
    rebind_result: "重新核對異動結果",
    edit: "更新負責人／期限",
    note: "追加聯絡／處理紀錄",
    safety_assistance: "記錄立即協助",
    assess: "核對條件與金額",
    decide: "記錄客人決定",
    start: "記錄開始處理",
    supplier_result: "記錄供應商實際結果",
    settle: "記錄實際收退款",
    void_settlement: "更正錯誤收付紀錄",
    resolve: "完成工作單",
    reopen: "重新開單核對",
    withdraw: "撤回尚未處理需求",
  };
  const moneyKinds = {
    customer_receipt: "本單需收客人",
    customer_refund: "本單需退客人",
    supplier_payment: "本單需付供應商",
    supplier_refund: "本單供應商需退款",
  };
  const path = (c) => `/api/mom/cases/${encodeURIComponent(c)}`;
  const date = (v) =>
    new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(v));
  const note = (t) => `<p class="muted preserve-lines">${E(t)}</p>`;
  const warn = (t) => `<div class="notice-card warn">${E(t)}</div>`;
  const button = (label, action, c, id = "", extra = "") =>
    `<button type="button" class="secondary-button" data-action="${action}" data-case-id="${E(c)}" data-id="${E(id)}" ${extra}>${E(label)}</button>`;
  const input = (label, name, value = "", attrs = "required") =>
    A.field(label, name, value, attrs);
  const text = (label, name, value = "", required = true, max = 4000) =>
    `<label><span>${E(label)}</span><textarea name="${name}" rows="3" maxlength="${max}" ${required ? "required" : ""}>${E(value)}</textarea></label>`;
  const check = (name, label, required = true) =>
    `<label class="checkbox-pill"><input name="${name}" type="checkbox" ${required ? "required" : ""}>${E(label)}</label>`;
  const select = (label, name, choices, value = "") =>
    `<label><span>${E(label)}</span><select name="${name}" required>${Object.entries(
      choices,
    )
      .map(
        ([k, v]) =>
          `<option value="${E(k)}" ${k === value ? "selected" : ""}>${E(v)}</option>`,
      )
      .join("")}</select></label>`;
  const proof = () =>
    input(
      "核對依據（對話、合約、收據或供應商通知）",
      "reference",
      "",
      'required maxlength="500"',
    ) +
    input(
      "實際處理時間（裝置時區）",
      "occurred_at",
      A.localDateTime(),
      'type="datetime-local" required',
    ) +
    check("checked", "我已核對實際情況與上述依據。");
  const key = (c) => "travel-service-intents:" + c;
  function pending(c) {
    try {
      return JSON.parse(sessionStorage.getItem(key(c)) || "[]");
    } catch {
      return [];
    }
  }
  function retain(c, item) {
    const items = pending(c).filter((v) => v.request_id !== item.request_id);
    items.push(item);
    sessionStorage.setItem(key(c), JSON.stringify(items));
  }
  function forget(c, id) {
    const items = pending(c).filter((v) => v.request_id !== id);
    if (items.length) sessionStorage.setItem(key(c), JSON.stringify(items));
    else sessionStorage.removeItem(key(c));
  }
  async function recover(c) {
    let committed = 0;
    for (const item of pending(c)) {
      const result = await A.api(
        `${path(c)}/service-order-receipts/${item.request_id}`,
      );
      if (result.committed) {
        forget(c, item.request_id);
        committed++;
      }
    }
    return committed;
  }
  function focus(selector) {
    requestAnimationFrame(() => {
      const el =
        $("#sheetBody")?.querySelector(selector) ||
        $("#sheetBody h3") ||
        $("#sheetTitle");
      if (el) {
        if (!el.matches("button,input,select,textarea")) el.tabIndex = -1;
        el.focus({ preventScroll: true });
      }
    });
  }
  function row(c, o) {
    return `<article class="operation-record service-order" data-order-id="${E(o.id)}"><div class="card-top"><h3>${E(o.title)}</h3><span class="case-status">${E(states[o.status])}</span></div>${note(`${kinds[o.kind]} · ${o.owner}${o.urgency === "urgent" ? " · 緊急" : ""}\n期限：${date(o.due_at)}（台北）`)}${o.end_trip ? warn("此單已記錄旅行取消；請核對案件款項後使用「取消旅行結案」。") : ""}${o.status === "completed" && !o.financial_current ? warn("已完成後款項或採用報價變更，請重新開單核對。") : ""}${button("查看與處理", "service-detail", c, o.id)}</article>`;
  }
  function listing(c, b, recovered = 0) {
    return `<h3 tabindex="-1">改退與旅中工作單</h3>${note("接住客人需求、供應商條件、客人決定、實際結果及收退款。供應商操作、緊急聯絡與銀行轉帳請依原流程完成。")}${recovered ? warn("已確認上次工作單儲存成功，沒有再次送出。") : ""}${pending(c).length ? warn("有上次尚未確認的操作。請打開原工作單重新核對並填寫；系統保留重試編號，避免重複儲存。") : ""}${b.case.status === "closed" ? warn("案件已結案，工作單僅供查看。") : button("新增改退／旅中工作單", "service-form", c, "", 'data-intent="create"')}${
      b.service_orders.length
        ? b.service_orders
            .slice()
            .reverse()
            .map((o) => row(c, o))
            .join("")
        : '<div class="empty-state">尚無工作單。收到改期、取消、退款需求或旅中事件時，從這裡開始。</div>'
    }`;
  }
  async function open(c, id = "", focusTo = "") {
    const generation = A.beginSheetRequest();
    if (generation === null) return;
    if (
      !A.openSheet(
        "改退與旅中工作單",
        '<p role="status">正在讀取工作單…</p>',
        true,
        "deadlines",
        c,
        generation,
      )
    )
      return;
    const stamp = A.currentSheetGeneration();
    try {
      const recovered = await recover(c),
        b = await A.api(`${path(c)}/operations`);
      if (!A.sheetRequestCurrent(stamp)) return;
      const o = b.service_orders.find((v) => v.id === id);
      $("#sheetBody").innerHTML =
        id && o ? detail(c, b, o) : listing(c, b, recovered);
      if (id && !o)
        $("#sheetBody").insertAdjacentHTML(
          "afterbegin",
          warn("這筆工作單已不存在。以下是目前案件紀錄。"),
        );
      A.setSheetBack(
        () => (id ? open(c, "", `[data-id="${id}"]`) : A.openCase(c)),
        id ? "返回工作單列表" : "返回案件",
      );
      if (focusTo) {
        const el = $("#sheetBody")?.querySelector(focusTo);
        el?.closest("details")?.setAttribute("open", "");
        focus(focusTo);
      } else focus("h3");
    } catch (err) {
      if (err instanceof A.ReauthenticationError) return;
      if (A.sheetRequestCurrent(stamp)) {
        $("#sheetBody").innerHTML =
          `<div role="alert" tabindex="-1" class="notice-card warn">${E(A.friendlyError(err))}</div>${button("重新讀取工作單", "service-detail", c, id)}${button("返回期限待辦", "ops-open", c, "", 'data-module="tasks"')}`;
        focus("[role=alert]");
      }
    }
  }
  function amounts(o) {
    return (o.assessment?.amounts || [])
      .map(
        (a) =>
          `<article class="operation-record"><h4>${E(a.currency)} 核對金額</h4>${Object.entries(
            moneyKinds,
          )
            .map(
              ([k, label]) =>
                `<div class="money-row"><span>${E(label)}／尚待</span><b>${E(a[k])}／${E(o.cash.remaining[a.currency]?.[k] || "0.00")}</b></div>`,
            )
            .join(
              "",
            )}${note(`供應商費用 ${a.supplier_fee} · 旅行社費用 ${a.agency_fee}\n整個案件最後應收（已含費用）：${a.final_customer_due}`)}</article>`,
      )
      .join("");
  }
  function assessmentSummary(o) {
    const a = o.assessment;
    return a
      ? `<div class="notice-card">${note(`供應商回覆：${a.supplier_reply}\n方案：${a.proposal}\n適用條件依據：${a.terms_reference}\n有效至：${date(a.valid_until)}（台北）`)}${a.terms_url ? `<a href="${E(a.terms_url)}" target="_blank" rel="noopener">查看條件來源 ↗</a>` : ""}${amounts(o)}</div>`
      : "";
  }
  function actionList(c, o) {
    const next = o.next_action;
    const main =
      next === "pretrip"
        ? button(
            "下一步：核對新版行前文件／交付",
            "ops-open",
            c,
            "",
            'data-module="pretrip"',
          )
        : next
          ? button(
              `下一步：${actions[next]}`,
              "service-form",
              c,
              o.id,
              `data-intent="${next}"`,
            )
          : "";
    const others = o.actions.filter((k) => k !== next);
    return (
      (main ? `<div class="service-next">${main}</div>` : "") +
      (others.length
        ? `<details class="service-secondary"><summary>其他處理與紀錄</summary><div class="operation-actions">${others.map((k) => button(actions[k], "service-form", c, o.id, `data-intent="${k}" ${k === "resolve" && o.resolution_blockers.length ? "disabled" : ""}`)).join("")}</div></details>`
        : "")
    );
  }
  function detail(c, b, o) {
    const a = o.assessment;
    return `<h3 tabindex="-1">${E(o.title)}</h3><span class="case-status">${E(states[o.status])}</span>${note(`${kinds[o.kind]} · ${o.owner} · ${o.urgency === "urgent" ? "緊急" : "一般"}\n期限：${date(o.due_at)}（台北）\n${o.request_details}`)}${o.contact ? `<p class="muted preserve-lines" data-service-contact>聯絡／緊急窗口：${E(o.contact)}</p>` : ""}${b.case.status === "closed" ? warn("案件已結案，以下僅供核對歷史。") : ""}${a && !o.assessment_current ? warn("核對後案件或訂購已變更。新處理開始前請重新核對方案；已發生的供應商結果與款項仍保留。") : ""}${o.assessment_expired ? warn("核對條件已過期，不能新增採用或開始處理。已開始的實際處理仍可追蹤。") : ""}${actionList(c, o)}${o.resolution_blockers.length ? `<details open><summary>完成前還需要</summary>${o.resolution_blockers.map(warn).join("")}</details>` : ""}${a ? `<details open><summary>目前核對方案</summary>${assessmentSummary(o)}${o.decision ? note(`客人決定：${o.decision.decision === "approved" ? "採用" : "未採用"}\n${o.decision.customer_reply}`) : ""}</details>` : ""}${o.supplier_result ? `<details open><summary>供應商實際結果（追加更正保留原紀錄）</summary>${note(`${o.supplier_result.outcome === "confirmed" ? "已確認處理" : "供應商未能承辦"}\n${o.supplier_result.details}\n依據：${o.supplier_result.reference}`)}</details>` : ""}<details><summary>實際收退款 · ${o.settlements.length} 筆</summary>${o.settlements.map((e) => note(`${e.currency} ${e.amount} · ${moneyKinds[e.kind]} · ${e.status === "voided" ? "已作廢" : "已記錄"}\n${e.reference}\n${e.memo}`)).join("") || note("尚無實際款項。")}</details><details><summary>完整處理歷史 · ${o.history.length} 筆</summary>${o.history
      .slice()
      .reverse()
      .map((h) =>
        note(
          `${date(h.occurred_at || h.at)}（台北） · ${h.actor}\n${actions[h.action] || { create: "建立需求", assessment: "核對方案", decision: "客人決定", settlement: "實際收退款", patch: "更新負責人／期限", contact_supplier: "聯絡供應商", contact_customer: "聯絡客人", correction: "追加更正" }[h.action] || h.action}\n${h.reference || ""}\n${historyText(h.data || {})}`,
        ),
      )
      .join("")}</details>`;
  }
  function historyText(data) {
    const fields = {
      reason: "原因",
      message: "處理內容",
      supplier_reply: "供應商回覆",
      proposal: "方案",
      terms_reference: "條件依據",
      customer_reply: "客人回覆",
      details: "實際結果",
      summary: "完成摘要",
      owner: "負責人",
      memo: "收付說明",
    };
    const lines = Object.entries(fields)
      .filter(([k]) => data[k])
      .map(([k, label]) => `${label}：${data[k]}`);
    if (data.valid_until)
      lines.push(`條件有效至：${date(data.valid_until)}（台北）`);
    if (data.due_at) lines.push(`期限：${date(data.due_at)}（台北）`);
    if (data.amount) lines.push(`實際金額：${data.currency} ${data.amount}`);
    if (data.amounts)
      lines.push(
        ...data.amounts.map(
          (a) =>
            `${a.currency} · 最後應收 ${a.final_customer_due} · 收客人 ${a.customer_receipt} · 退客人 ${a.customer_refund} · 付供應商 ${a.supplier_payment} · 供應商退款 ${a.supplier_refund}`,
        ),
      );
    return lines.join("\n");
  }
  const bookingChoices = (b, name, selected = [], eligible = null) =>
    `<fieldset class="full"><legend>${name === "booking_ids" ? "關聯原訂購（改期／取消必選）" : "供應商處理後目前有效的訂購"}</legend>${
      b.bookings
        .filter(
          (v) =>
            v.status === "confirmed" && (!eligible || eligible.includes(v.id)),
        )
        .map(
          (v) =>
            `<label class="checkbox-pill"><input type="checkbox" name="${name}" value="${E(v.id)}" ${selected.includes(v.id) ? "checked" : ""}>${E(v.title)} · ${E(v.confirmation_number)}</label>`,
        )
        .join("") || note("尚無有效訂購；可建立退款或旅中事件工作單。")
    }</fieldset>`;
  const cashFields = (a, i) =>
    `<fieldset class="service-money full" data-money-row><legend>核對金額（不自動換匯）</legend>${input("幣別", `currency_${i}`, a.currency, 'required pattern="[A-Z]{3}" maxlength="3"')}${Object.entries(
      {
        ...moneyKinds,
        supplier_fee: "供應商費用（說明，已含於收付總額）",
        agency_fee: "旅行社費用（說明，已含於收付總額）",
        final_customer_due: "整個案件最後應收總額（已含費用，非本單差額）",
      },
    )
      .map(([k, label]) =>
        input(
          label,
          `${k}_${i}`,
          a[k] || "0.00",
          'type="number" min="0" step="0.01" required',
        ),
      )
      .join(
        "",
      )}${button("移除此幣別", "service-remove-currency", "")}</fieldset>`;
  async function form(c, id, intent) {
    const generation = A.beginSheetRequest();
    if (generation === null) return;
    const b = await A.api(`${path(c)}/operations`),
      o = b.service_orders.find((v) => v.id === id);
    if (!A.sheetRequestCurrent(generation)) return;
    if (b.case.status === "closed")
      throw new Error("案件已結案，請先重新開案。");
    if (intent !== "create" && (!o || !o.actions.includes(intent)))
      throw new Error("此操作已變更，請重新開啟工作單核對。");
    let body = "",
      build,
      endpoint = intent,
      method = "POST";
    const common = (v) => ({
      reference: v.reference,
      occurred_at: new Date(v.occurred_at).toISOString(),
      checked: v.checked === "on",
    });
    if (intent === "create") {
      body =
        select("工作類型", "kind", kinds, "incident") +
        input("工作單名稱", "title", "", 'required maxlength="160"') +
        text("客人需求／事件狀況", "request_details") +
        input("負責人", "owner", "媽媽", 'required maxlength="100"') +
        input(
          "回覆／處理期限（裝置時區）",
          "due_at",
          A.localDateTime(new Date(Date.now() + 3600000)),
          'type="datetime-local" required',
        ) +
        select("急迫程度", "urgency", { normal: "一般", urgent: "緊急" }) +
        text(
          "聯絡／緊急窗口（選填，登入失效時會清除未存內容）",
          "contact",
          "",
          false,
          500,
        ) +
        bookingChoices(b, "booking_ids");
      build = (v, f) => ({
        ...common(v),
        kind: v.kind,
        title: v.title,
        request_details: v.request_details,
        owner: v.owner,
        due_at: new Date(v.due_at).toISOString(),
        urgency: v.urgency,
        contact: v.contact,
        booking_ids: new FormData(f).getAll("booking_ids"),
      });
      endpoint = "";
    } else if (intent === "edit") {
      body =
        input("負責人", "owner", o.owner, 'required maxlength="100"') +
        input(
          "處理期限（裝置時區）",
          "due_at",
          A.localDateTime(new Date(o.due_at)),
          'type="datetime-local" required',
        ) +
        select(
          "急迫程度",
          "urgency",
          { normal: "一般", urgent: "緊急" },
          o.urgency,
        ) +
        text("聯絡／緊急窗口", "contact", o.contact, false, 500) +
        text("更新原因", "reason", "", true, 500);
      build = (v) => ({
        ...common(v),
        owner: v.owner,
        due_at: new Date(v.due_at).toISOString(),
        urgency: v.urgency,
        contact: v.contact,
        reason: v.reason,
      });
      endpoint = "";
      method = "PATCH";
    } else if (intent === "assess") {
      const a = o.assessment || {},
        amounts = a.amounts?.length
          ? a.amounts
          : Object.entries(b.balances).map(([currency, v]) => ({
              currency,
              final_customer_due: v.expected_customer_total || "0.00",
            }));
      body =
        warn(
          "先核對本產品適用的合約、供應商政策與時效。此處手續費為說明，不會再加到收付總額。方案重核會清除原採用與開始授權，供應商實際結果和已收付款保留。",
        ) +
        text("供應商條件與回覆", "supplier_reply", a.supplier_reply) +
        text("提供客人的完整處理方案", "proposal", a.proposal) +
        input(
          "適用合約／供應商條件依據",
          "terms_reference",
          a.terms_reference,
          'required maxlength="500"',
        ) +
        input(
          "條件來源網址（選填）",
          "terms_url",
          a.terms_url || "",
          'type="url" maxlength="2000"',
        ) +
        input(
          "條件有效至（裝置時區）",
          "valid_until",
          A.localDateTime(
            a.valid_until
              ? new Date(a.valid_until)
              : new Date(Date.now() + 3600000),
          ),
          'type="datetime-local" required',
        ) +
        text("本次核對／修正原因", "reason", "", true, 500) +
        `<div id="serviceAmounts" class="full">${amounts.map(cashFields).join("")}</div>` +
        button("增加幣別金額", "service-add-currency", c) +
        note(
          "無款項的事件可不填金額。有旅行取消或款項時，逐幣別填整個案件最後應收與本單四個方向總額；分批款項稍後記錄。",
        );
      build = (v, f) => ({
        ...common(v),
        supplier_reply: v.supplier_reply,
        proposal: v.proposal,
        terms_reference: v.terms_reference,
        terms_url: v.terms_url || null,
        valid_until: new Date(v.valid_until).toISOString(),
        reason: v.reason,
        amounts: [...f.querySelectorAll("[data-money-row]")].map((_, i) =>
          Object.fromEntries(
            [
              "currency",
              ...Object.keys(moneyKinds),
              "supplier_fee",
              "agency_fee",
              "final_customer_due",
            ].map((k) => [k, v[`${k}_${i}`]]),
          ),
        ),
      });
      endpoint = "assessment";
    } else if (intent === "decide") {
      body =
        assessmentSummary(o) +
        select("客人決定", "decision", {
          approved: "客人採用本次方案",
          declined: "客人不採用",
        }) +
        text("客人實際回覆", "customer_reply");
      build = (v) => ({
        ...common(v),
        assessment_revision: o.assessment.revision,
        decision: v.decision,
        customer_reply: v.customer_reply,
      });
      endpoint = "decision";
    } else if (intent === "start") {
      body =
        assessmentSummary(o) +
        warn(
          "請先在供應商原系統開始辦理，核對授權與條件期限後記錄。這個按鈕不會替您改票、取消或轉帳。",
        );
      build = (v) => ({ ...common(v), stage: "start" });
      endpoint = "progress";
    } else if (intent === "supplier_result") {
      body =
        select("供應商實際結果", "outcome", {
          confirmed: "已確認實際完成",
          declined: "供應商未能承辦",
        }) +
        text("通知內容、異動後狀況與依據", "details") +
        (o.kind === "change"
          ? warn(
              "先至「訂購確認」重新核對沿用訂購，或作廢被替換的本站紀錄並登錄新訂購；之後回本單選取實際結果。",
            ) +
            bookingChoices(
              b,
              "result_booking_ids",
              [],
              o.eligible_result_booking_ids,
            )
          : o.kind === "cancellation"
            ? warn(
                "僅在供應商已確認取消後送出。本站會停用此單所有關聯訂購；單純作廢錯誤紀錄不算供應商取消。",
              ) +
              o.booking_ids
                .map((id) =>
                  note(b.bookings.find((v) => v.id === id)?.title || id),
                )
                .join("")
            : "");
      build = (v, f) => ({
        ...common(v),
        stage: "supplier_result",
        outcome: v.outcome,
        details: v.details,
        booking_revisions:
          o.kind === "cancellation" && v.outcome === "confirmed"
            ? Object.fromEntries(
                o.booking_ids.map((id) => [
                  id,
                  b.bookings.find((v) => v.id === id)?.revision,
                ]),
              )
            : {},
        result_booking_ids:
          v.outcome === "confirmed"
            ? new FormData(f).getAll("result_booking_ids")
            : [],
      });
      endpoint = "progress";
    } else if (intent === "rebind_result") {
      body =
        warn(
          "核對最新有效訂購，追加本次重新核對依據。原供應商結果與舊關聯均保留於歷史；不會重新辦理供應商異動。",
        ) +
        bookingChoices(
          b,
          "result_booking_ids",
          [],
          o.eligible_result_booking_ids,
        ) +
        text("重新核對異動結果的原因／內容", "details");
      build = (v, f) => ({
        ...common(v),
        stage: "rebind_result",
        details: v.details,
        result_booking_ids: new FormData(f).getAll("result_booking_ids"),
      });
      endpoint = "progress";
    } else if (intent === "settle") {
      body =
        warn(
          "只記錄已實際完成的款項。尚待金額不等於已付款；可分批填寫，不會執行銀行轉帳。",
        ) +
        amounts(o) +
        select("實際收付方向", "kind", moneyKinds) +
        select(
          "幣別",
          "currency",
          Object.fromEntries(Object.keys(o.cash.remaining).map((c) => [c, c])),
        ) +
        input(
          "本次實際金額",
          "amount",
          "",
          'type="number" min="0.01" step="0.01" required',
        ) +
        text("收付說明", "memo", "", false, 1000);
      build = (v) => ({
        ...common(v),
        kind: v.kind,
        currency: v.currency,
        amount: v.amount,
        memo: v.memo,
      });
      endpoint = "settlement";
    } else if (intent === "void_settlement") {
      body =
        warn(
          "選取金額或依據錯誤的本站紀錄作廢，再另記錄正確金額。實際款項不會被取消或轉回。",
        ) +
        select(
          "要更正的實際收付",
          "entry_id",
          Object.fromEntries(
            o.settlements
              .filter((e) => e.status !== "voided")
              .map((e) => [
                e.id,
                `${e.currency} ${e.amount} · ${moneyKinds[e.kind]} · ${e.reference}`,
              ]),
          ),
        ) +
        text("更正原因", "reason", "", true, 500);
      build = (v) => ({
        ...common(v),
        stage: "void_settlement",
        entry_id: v.entry_id,
        reason: v.reason,
      });
      endpoint = "progress";
    } else if (intent === "resolve") {
      body =
        text("處理結果與回覆客人摘要", "summary") +
        check("customer_notified_checked", "我已將實際處理結果通知客人。") +
        (["cancellation", "refund"].includes(o.kind)
          ? check(
              "end_trip",
              "此次整趟旅行已取消，所有有效訂購均已停止；案件後續使用取消旅行結案。",
              false,
            )
          : "");
      build = (v) => ({
        ...common(v),
        summary: v.summary,
        customer_notified_checked: v.customer_notified_checked === "on",
        end_trip: v.end_trip === "on",
      });
    } else if (["withdraw", "reopen"].includes(intent)) {
      body =
        text(
          intent === "withdraw" ? "撤回原因" : "重新開單原因",
          "reason",
          "",
          true,
          500,
        ) +
        warn(
          "原供應商結果、核對歷史與實際款項均保留。重新開單後如需新增處理／款項，請重新核對方案與客人決定。",
        );
      build = (v) => ({
        ...common(v),
        ...(intent === "withdraw" ? { stage: "withdraw" } : {}),
        reason: v.reason,
      });
      endpoint = intent === "withdraw" ? "progress" : "reopen";
    } else {
      body =
        (intent === "note"
          ? select("紀錄種類", "stage", {
              note: "處理備註",
              contact_supplier: "已聯絡供應商",
              contact_customer: "已聯絡客人",
              correction: "追加更正（保留原結果）",
            })
          : warn(
              "緊急事件請先依原流程協助安全、醫療與聯絡，再記錄處理；無須等費用方案或客人採用。",
            )) + text("實際聯絡／協助內容", "message");
      build = (v) => ({
        ...common(v),
        stage: intent === "note" ? v.stage : "safety_assistance",
        message: v.message,
      });
      endpoint = "progress";
    }
    if (
      !A.openSheet(
        intent === "create" ? "新增改退／旅中工作單" : actions[intent],
        `<form id="serviceOrderForm" class="form-grid">${body}${proof()}<div class="full" id="serviceConflict"></div><button type="submit" class="primary-button full">${E(intent === "create" ? "儲存需求" : actions[intent])}</button></form>`,
        true,
        "deadlines",
        c,
        generation,
      )
    )
      return;
    const f = $("#serviceOrderForm");
    if (intent === "create") {
      const update = () => {
        const chosen = f.elements.kind.value,
          refs = [...f.querySelectorAll("[name=booking_ids]")];
        refs.forEach((el) => {
          el.disabled =
            chosen === "change" &&
            !b.eligible_service_booking_ids.includes(el.value);
          if (el.disabled) el.checked = false;
        });
        const required =
          ["change", "cancellation"].includes(chosen) &&
          !refs.some((el) => el.checked && !el.disabled);
        if (refs[0]) refs[0].required = required;
      };
      f.addEventListener("change", update);
      update();
    }
    f.serviceOperation = {
      c,
      id,
      intent,
      build,
      endpoint,
      method,
      revision: o?.revision,
      assessmentRevision: o?.assessment?.revision,
      bookings: JSON.stringify(
        o?.booking_ids.map((id) => [
          id,
          b.bookings.find((v) => v.id === id)?.revision,
        ]),
      ),
      stamp: A.currentSheetGeneration(),
      request: null,
      locked: false,
    };
    A.setSheetBack(
      () => open(c, id, `[data-intent="${intent}"]`),
      "返回" + (id ? "工作單" : "工作單列表"),
    );
  }
  async function refreshConflict(f, op) {
    const b = await A.api(`${path(op.c)}/operations`),
      o = b.service_orders.find((v) => v.id === op.id);
    const refs = JSON.stringify(
      o?.booking_ids.map((id) => [
        id,
        b.bookings.find((v) => v.id === id)?.revision,
      ]),
    );
    const consequential = [
      "decide",
      "start",
      "supplier_result",
      "rebind_result",
      "settle",
      "resolve",
    ].includes(op.intent);
    op.locked =
      !o ||
      b.case.status === "closed" ||
      !o.actions.includes(op.intent) ||
      (consequential &&
        (o.assessment?.revision !== op.assessmentRevision ||
          refs !== op.bookings));
    if (o && !op.locked) op.revision = o.revision;
    $("#serviceConflict").innerHTML =
      warn(
        `目前狀態：${states[o?.status] || "已不存在"}${o ? " · " + o.owner + " · " + date(o.due_at) : ""}。填寫內容已保留。`,
      ) +
      (o?.resolution_blockers || []).map(warn).join("") +
      (op.locked
        ? button("返回最新工作單核對", "service-detail", op.c, op.id)
        : check(
            "review_latest",
            "我已核對最新狀態與上方內容，確認本次紀錄仍適用。",
          ));
  }
  async function submit(f) {
    const op = f.serviceOperation;
    if (op.locked)
      throw new Error(
        "方案、訂購或可用操作已變更，請返回最新工作單核對；本次未儲存。",
      );
    const stored = pending(op.c).find(
      (v) => v.order_id === op.id && v.intent === op.intent,
    );
    if (stored) {
      const result = await A.api(
        `${path(op.c)}/service-order-receipts/${stored.request_id}`,
      );
      if (result.committed) {
        forget(op.c, stored.request_id);
        A.showToast(
          "已確認上次保存成功；接下來顯示上次實際保存的內容，請核對後再修改。",
        );
        return saved(f, op, result.order_id, true);
      }
    }
    const v = Object.fromEntries(new FormData(f)),
      payload = op.frozenPayload || {
        ...op.build(v, f),
        ...(op.id ? { expected_revision: op.revision } : {}),
      };
    op.frozenPayload = payload;
    const request = op.request || stored?.request_id || crypto.randomUUID();
    op.request = request;
    retain(op.c, { request_id: request, order_id: op.id, intent: op.intent });
    try {
      const result = await A.api(
        `${path(op.c)}/service-orders${op.id ? "/" + encodeURIComponent(op.id) : ""}${op.endpoint ? "/" + op.endpoint : ""}`,
        {
          method: op.method,
          body: JSON.stringify({ ...payload, request_id: request }),
        },
      );
      forget(op.c, request);
      await saved(f, op, result.id);
    } catch (err) {
      if (err.status >= 400 && err.status < 500) {
        f.dataset.uncertain = "false";
        op.frozenPayload = null;
        f.querySelectorAll("input,select,textarea").forEach((el) => {
          el.disabled = false;
        });
        f.querySelector("[data-action=service-reconcile]")?.remove();
        forget(op.c, request);
        op.request = null;
        if (err.status === 409 && op.id) {
          try {
            await refreshConflict(f, op);
          } catch (refreshError) {
            if (refreshError instanceof A.ReauthenticationError)
              throw refreshError;
            $("#serviceConflict").innerHTML = warn(
              "最新內容暫時無法讀取。原填寫保留，請稍後返回工作單核對。",
            );
            op.locked = true;
          }
        }
      }
      if (!err.status || err.status >= 500) {
        f.dataset.uncertain = "true";
        if (!f.querySelector("[data-action=service-reconcile]"))
          f.insertAdjacentHTML(
            "beforeend",
            warn(
              "尚未確認上次儲存結果。填寫內容暫時鎖定，先確認結果，避免將修改後的文字誤認為已保存。",
            ) + button("確認上次儲存結果", "service-reconcile", op.c, op.id),
          );
      }
      throw err;
    }
  }
  async function saved(f, op, id, recovered = false) {
    A.markFormCommitted(f, "service-detail", { caseId: op.c, id });
    f.dataset.dirty = "false";
    if (!recovered)
      A.showToast("工作單已保存。供應商與轉帳作業仍依原流程辦理。");
    if (A.sheetRequestCurrent(op.stamp) && f.isConnected)
      await open(op.c, id, `[data-intent="${op.intent}"]`);
    await A.loadHome();
    await A.loadCases();
  }
  A.registerAction("service-open", (el) => open(el.dataset.caseId));
  A.registerAction("service-detail", (el) =>
    open(el.dataset.caseId, el.dataset.id),
  );
  A.registerAction("service-form", (el) =>
    form(el.dataset.caseId, el.dataset.id, el.dataset.intent),
  );
  A.registerAction("service-add-currency", () => {
    const target = $("#serviceAmounts"),
      i = target.querySelectorAll("[data-money-row]").length;
    if (i >= 10) throw new Error("每單最多核對 10 個幣別。");
    target.insertAdjacentHTML(
      "beforeend",
      cashFields({ currency: "", final_customer_due: "0.00" }, i),
    );
    $("#serviceOrderForm").dataset.dirty = "true";
    target.querySelectorAll("[name^=currency_]")[i].focus();
  });
  A.registerAction("service-remove-currency", (el) => {
    const f = $("#serviceOrderForm");
    if (f.dataset.busy === "true" || f.dataset.uncertain === "true") return;
    el.closest("[data-money-row]").remove();
    f.querySelectorAll("[data-money-row]").forEach((row, i) =>
      row.querySelectorAll("input").forEach((input) => {
        input.name = input.name.replace(/_\d+$/, `_${i}`);
      }),
    );
    f.dataset.dirty = "true";
    f.querySelector("[data-action=service-add-currency]").focus();
  });
  A.registerAction("service-reconcile", () => {
    const f = $("#serviceOrderForm");
    if (f.dataset.busy === "true") return;
    f.requestSubmit();
  });
  A.registerForm("serviceOrderForm", submit);
  window.addEventListener("travel-auth-expired", () => {
    const f = $("#serviceOrderForm");
    if (f?.elements.contact) f.elements.contact.value = "";
    if (f?.serviceOperation.frozenPayload?.contact)
      f.serviceOperation.frozenPayload.contact = "";
    document
      .querySelectorAll("[data-service-contact]")
      .forEach((el) => el.remove());
  });
})();

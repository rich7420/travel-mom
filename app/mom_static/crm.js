"use strict";
(() => {
  const A = window.MomApp,
    H = window.Assistance,
    E = A.escapeHtml,
    $ = (s) => document.querySelector(s);
  const kinds = {
    draft: "回覆草稿",
    incoming: "收到訊息",
    outgoing: "傳出訊息紀錄",
    contact: "聯絡備註",
    complaint: "客訴",
  };
  const channels = {
    manual: "手動整理",
    email: "Email",
    line: "LINE",
    phone: "電話",
    in_person: "當面",
  };
  const statuses = {
    draft: "草稿，尚未傳送",
    received: "已收到",
    recorded: "已保存，尚未確認傳送",
    noted: "聯絡備註",
    open: "客訴待處理",
    resolved: "客訴已處理",
    sent: "已人工送出",
    provider_accepted: "通道已受理（不代表對方已閱讀）",
  };
  const input = (label, name, value = "", attrs = "required") =>
    A.field(label, name, value, attrs);
  const row = (c, m) =>
    `<article class="operation-record"><h3>${E(kinds[m.kind])}</h3><p>${E(statuses[m.status] || m.status)} · ${E(channels[m.channel])}</p><p class="muted">${E(m.owner)}${m.followup_at ? ` · 追蹤：${E(new Date(m.followup_at).toLocaleString("zh-TW"))}` : ""}</p>${H.button("查看内容與歷史", "crm-reveal", c, m.id)}</article>`;
  async function open(c, service = "") {
    const ctx = H.context();
    if (!ctx) return;
    const recovered = await H.recover(c),
      b = await A.api(`${H.base(c)}/crm`);
    if (!H.current(ctx)) return;
    const customer = b.customer;
    const html =
      recovered +
      `<p class="muted">聯絡紀錄按明確關聯的客戶保存。複製與保存草稿不代表已傳送。${b.case_closed ? "本案已結案，仍可追加聯絡與客訴；業務結果保留。" : ""}</p><article class="operation-record"><h3>${customer ? E(customer.display_name) : "尚未關聯客戶"}</h3><div class="operation-actions">${H.button(customer ? "更正客戶關聯" : "選擇既有客戶", "crm-link-form", c)}${H.button("建立新客戶", "crm-customer-form", c)}${customer ? H.button("查看／修改聯絡資料", "crm-customer-form", c, customer.id) + H.button("Email 接收同意", "crm-consent-form", c, customer.id) + H.button("這位客戶的其他案件", "crm-customer-history", c, customer.id) : ""}</div></article>${customer ? H.button("新增聯絡／草稿／客訴", "crm-message-form", c, "", service ? `data-service-order-id="${E(service)}"` : "") : ""}<h3>聯絡紀錄</h3>${
        b.communications
          .filter((m) => !service || m.service_order_id === service)
          .map((m) => row(c, m))
          .join("") || '<p class="empty-state">尚無聯絡紀錄。</p>'
      }`;
    if (!A.openSheet("客戶與聯絡紀錄", html, true, "reply", c, ctx.generation))
      return;
    A.setSheetBack(() => A.openCase(c), "返回案件");
  }
  async function profile(el) {
    const c = el.dataset.caseId,
      id = el.dataset.id,
      ctx = H.context();
    if (!ctx) return;
    const value = id
      ? await A.api(`/api/mom/customers/${encodeURIComponent(id)}/reveal`, {
          headers: H.headers(ctx.privacy.actor),
        })
      : {};
    const scope = id || "new";
    await H.recover(scope, true);
    if (!H.current(ctx)) return;
    const body =
      input(
        "客戶顯示姓名（可搜尋）",
        "display_name",
        value.display_name || "",
        'required maxlength="160"',
      ) +
      input(
        "電話",
        "phone",
        value.phone || "",
        'maxlength="80" autocomplete="off"',
      ) +
      input(
        "Email",
        "email",
        value.email || "",
        'type="email" maxlength="254" autocomplete="off"',
      ) +
      `<label><span>客戶備註</span><textarea name="notes" maxlength="4000" rows="4">${E(value.notes || "")}</textarea></label><p class="muted">同名客戶不會自動合併。修改客戶資料後，相關提醒會暫停核對；更動 Email 另外撤銷原接收同意。</p>`;
    H.mount(
      ctx,
      c,
      id ? "修改客戶聯絡資料" : "建立客戶",
      "customerProfileForm",
      body,
      {
        scope,
        customer: true,
        caseId: c,
        target: id,
        action: "customer.profile.write",
        endpoint: `/api/mom/customers${id ? "/" + encodeURIComponent(id) : ""}`,
        method: id ? "PATCH" : "POST",
        revision: value.revision,
        returnAction: "crm-open",
      },
      () => open(c),
    );
  }
  async function link(el) {
    const c = el.dataset.caseId,
      ctx = H.context();
    if (!ctx) return;
    const b = await A.api(`${H.base(c)}/crm`),
      index = await A.api(
        `/api/mom/customers?q=${encodeURIComponent(el.dataset.query || "")}`,
      );
    if (
      el.dataset.customerId &&
      !index.customers.some((value) => value.id === el.dataset.customerId)
    )
      index.customers.push(
        await A.api(
          `/api/mom/customers/${encodeURIComponent(el.dataset.customerId)}`,
        ),
      );
    if (!H.current(ctx)) return;
    if (!index.customers.length) throw new Error("尚無客戶，請先建立新客戶。");
    const choices = Object.fromEntries(
      index.customers.map((v) => [
        v.id,
        `${v.display_name} · ${v.id.slice(-6)}`,
      ]),
    );
    H.mount(
      ctx,
      c,
      "明確關聯案件客戶",
      "customerLinkForm",
      input(
        "搜尋客戶姓名（最多顯示 100 筆）",
        "customer_query",
        el.dataset.query || "",
        'maxlength="160" autocomplete="off"',
      ) +
        H.button("搜尋既有客戶", "crm-link-search", c) +
        H.select(
          "客戶（同名時請核對聯絡資料）",
          "customer_id",
          choices,
          el.dataset.customerId || b.customer?.id,
        ) +
        input("關聯／更正原因", "reason", "", 'required maxlength="500"') +
        '<p class="muted">既有訊息保留原客戶歸屬，不會搬移舊歷史。</p>',
      {
        scope: c,
        action: "crm.link",
        endpoint: `${H.base(c)}/customer-link`,
        revision: b.customer_link?.revision || 0,
      },
      () => open(c),
    );
  }
  async function consent(el) {
    const c = el.dataset.caseId,
      id = el.dataset.id,
      ctx = H.context();
    if (!ctx) return;
    const value = await A.api(`/api/mom/customers/${encodeURIComponent(id)}`);
    if (!H.current(ctx)) return;
    H.mount(
      ctx,
      c,
      "記錄客戶 Email 接收同意",
      "customerConsentForm",
      `<p>${E(value.display_name)} · ${value.consents.email?.granted ? "目前已同意" : "目前未同意"}</p>` +
        H.select(
          "實際核對結果",
          "granted",
          { true: "客戶已同意接收 Email 提醒", false: "撤回／未同意" },
          String(value.consents.email?.granted || false),
        ),
      {
        scope: id,
        customer: true,
        caseId: c,
        action: "customer.consent",
        endpoint: `/api/mom/customers/${encodeURIComponent(id)}/consents`,
        revision: value.revision,
      },
      () => open(c),
    );
  }
  async function messageForm(el) {
    const editor = document.querySelector("#crmMessageBody"),
      edited = editor?.value;
    const c = el.dataset.caseId,
      id = el.dataset.id,
      ctx = H.context(id ? editor : null);
    if (!ctx) return;
    const value = id
      ? await A.api(
          `${H.base(c)}/communications/${encodeURIComponent(id)}/reveal`,
          { headers: H.headers(ctx.privacy.actor) },
        )
      : {};
    if (!H.current(ctx)) return;
    if (id && value.status === "draft" && edited !== undefined)
      value.body = edited;
    let body = id
      ? `<p>${E(kinds[value.kind])}</p>`
      : H.select("紀錄種類", "kind", kinds, el.dataset.kind || "contact") +
        H.select("聯絡方式", "channel", channels);
    if (!id || value.status === "draft")
      body += H.text(
        "訊息／聯絡内容",
        "body",
        value.body || el.draftBody || "",
      );
    else
      body += `<p class="preserve-lines">${E(value.body)}</p><p class="muted">原文保留，需更正請追加新紀錄。</p>`;
    body +=
      input(
        "負責人",
        "owner",
        value.owner || "媽媽",
        'required maxlength="100"',
      ) +
      input(
        "追蹤期限（可留空）",
        "followup_at",
        value.followup_at ? A.localDateTime(value.followup_at) : "",
        'type="datetime-local"',
      );
    if (value.kind === "complaint")
      body += H.select(
        "客訴處理狀態",
        "status",
        { open: "待處理", resolved: "已處理" },
        value.status,
      );
    H.mount(
      ctx,
      c,
      id ? "修改草稿／客訴追蹤" : "新增聯絡紀錄",
      "communicationForm",
      body,
      {
        scope: c,
        target: id,
        action: `crm.message.${id || "create"}`,
        endpoint: `${H.base(c)}/communications${id ? "/" + encodeURIComponent(id) : ""}`,
        method: id ? "PATCH" : "POST",
        revision: value.revision,
        service: el.dataset.serviceOrderId || null,
        corrects: el.dataset.correctsId || null,
      },
      () => open(c),
      "保存（不會傳送）",
    );
  }
  async function reveal(el) {
    const c = el.dataset.caseId,
      id = el.dataset.id,
      ctx = H.context();
    if (!ctx) return;
    const m = await A.api(
      `${H.base(c)}/communications/${encodeURIComponent(id)}/reveal`,
      { headers: H.headers(ctx.privacy.actor) },
    );
    if (!H.current(ctx)) return;
    const body = `<div data-private><p>${E(statuses[m.status])} · ${E(m.owner)}</p><label><span>目前內容${m.status === "draft" ? "（複製前可暫時修改，需另存才會保留）" : ""}</span><textarea id="crmMessageBody" rows="10" ${m.status === "draft" ? 'data-dirty="true"' : "readonly"}>${E(m.body)}</textarea></label><div class="operation-actions">${H.button("複製目前内容", "crm-message-copy", c, id)}${m.status === "draft" || m.kind === "complaint" ? H.button("修改並保存", "crm-message-form", c, id) : ""}${["draft", "recorded"].includes(m.status) && ["draft", "outgoing"].includes(m.kind) ? H.button("記錄已人工送出", "crm-message-attest", c, id) : ""}${H.button("追加更正紀錄", "crm-message-form", c, "", `data-corrects-id="${E(id)}"`)}${H.button("返回聯絡紀錄", "crm-open", c)}</div><details><summary>歷史 · ${m.history.length} 筆</summary>${m.history.map((h) => `<article><p>${E(h.at)} · ${E(h.actor)}</p><p class="preserve-lines">${E(h.body)}</p></article>`).join("")}</details></div>`;
    if (A.openSheet(kinds[m.kind], body, true, "reply", c, ctx.generation))
      A.setSheetBack(() => open(c), "返回聯絡紀錄");
  }
  async function attest(el) {
    const c = el.dataset.caseId,
      id = el.dataset.id,
      ctx = H.context();
    if (!ctx) return;
    const m = await A.api(
      `${H.base(c)}/communications/${encodeURIComponent(id)}/reveal`,
      { headers: H.headers(ctx.privacy.actor) },
    );
    if (!H.current(ctx)) return;
    H.mount(
      ctx,
      c,
      "記錄已人工送出",
      "communicationAttestForm",
      `<p class="preserve-lines">${E(m.body)}</p><label class="checkbox-pill"><input type="checkbox" name="actually_sent" required>我已把這份已保存的原文實際傳给客戶（複製不算送出）。</label>`,
      {
        scope: c,
        target: id,
        action: `crm.message.${id}.sent`,
        endpoint: `${H.base(c)}/communications/${encodeURIComponent(id)}/attest`,
        revision: m.revision,
      },
      () => open(c),
    );
  }
  async function history(el) {
    const c = el.dataset.caseId,
      ctx = H.context();
    if (!ctx) return;
    const b = await A.api(
      `/api/mom/customers/${encodeURIComponent(el.dataset.id)}/history`,
    );
    if (!H.current(ctx)) return;
    if (
      A.openSheet(
        "這位客戶的案件與聯絡歷史",
        b.cases
          .map(
            (v) =>
              `<article class="operation-record"><h3>${E(v.customer_name)} · ${E(v.destination)}</h3>${H.button("開啟案件", "open-case", v.id)}</article>`,
          )
          .join("") +
          "<h3>歷史聯絡（保留原歸屬）</h3>" +
          b.communications.map((m) => row(m.case_id, m)).join(""),
        true,
        "reply",
        c,
        ctx.generation,
      )
    )
      A.setSheetBack(() => open(c), "返回客戶");
  }
  async function submit(form) {
    const v = Object.fromEntries(new FormData(form)),
      op = form.assistanceOperation;
    if (form.assistanceCommand?.frozen) {
      await H.submit(form, {}, op);
      await H.saved(form, "已核對上次保存結果。");
      return;
    }
    let data = { ...H.evidence(v) };
    if (form.id === "customerProfileForm")
      data = {
        ...data,
        display_name: v.display_name,
        phone: v.phone,
        email: v.email,
        notes: v.notes,
        ...(op.revision ? { expected_revision: op.revision } : {}),
      };
    if (form.id === "customerLinkForm")
      data = {
        ...data,
        customer_id: v.customer_id,
        reason: v.reason,
        expected_revision: op.revision,
      };
    if (form.id === "customerConsentForm")
      data = {
        ...data,
        channel: "email",
        granted: v.granted === "true",
        expected_revision: op.revision,
      };
    if (["communicationForm", "replySaveForm"].includes(form.id)) {
      data = {
        ...data,
        owner: v.owner,
        followup_at: v.followup_at
          ? new Date(v.followup_at).toISOString()
          : null,
      };
      if (op.revision)
        data = {
          ...data,
          expected_revision: op.revision,
          ...(v.body !== undefined ? { body: v.body } : {}),
          ...(v.status ? { status: v.status } : {}),
        };
      else
        data = {
          ...data,
          kind: v.kind || "draft",
          channel: v.channel || "manual",
          body: op.draftBody ?? v.body,
          service_order_id: op.service,
          corrects_id: op.corrects,
        };
    }
    if (form.id === "communicationAttestForm")
      data = {
        ...data,
        expected_revision: op.revision,
        actually_sent: v.actually_sent === "on",
      };
    const result = await H.submit(form, data, op);
    if (form.id === "customerProfileForm" && !op.target) {
      A.markFormCommitted(form, "crm-open", { caseId: op.caseId });
      form.dataset.dirty = "false";
      A.showToast("客戶已建立，請選擇並核對案件關聯。");
      await link({
        dataset: {
          caseId: op.caseId,
          customerId: result.id || result.record_id,
        },
      });
      return;
    }
    await H.saved(
      form,
      form.id === "communicationAttestForm"
        ? "已記錄實際人工送出。"
        : "已保存；草稿與紀錄不會自動傳送。",
    );
  }
  async function saveReply(el) {
    const c = el.dataset.caseId,
      editor = $("#replyDraft");
    if (!c || !editor) throw new Error("請先選擇案件，才能保存客戶草稿。");
    const current = editor.value,
      ctx = H.context(editor);
    if (!ctx) return;
    // Preserve exact current editor and existing feedback controls across cancel.
    const original = $("#sheetBody").innerHTML,
      privacy = ctx.privacy;
    const back = () => {
      if (!window.TravelPrivacy.current(privacy)) return;
      A.openSheet("回覆草稿", original, true, "reply", c);
      $("#replyDraft").value = current;
    };
    const b = await A.api(`${H.base(c)}/crm`);
    if (!H.current(ctx)) return;
    if (!b.customer)
      throw new Error("請先在案件「客戶與聯絡紀錄」建立客戶關聯，再保存草稿。");
    H.mount(
      ctx,
      c,
      "保存目前回覆草稿",
      "replySaveForm",
      '<p class="muted">保存目前修改後的文字，不會傳送給客戶。</p>' +
        input("負責人", "owner", "媽媽", 'required maxlength="100"'),
      {
        scope: c,
        action: "crm.message.create",
        endpoint: `${H.base(c)}/communications`,
        draftBody: current,
        service: null,
        corrects: null,
      },
      back,
      "保存草稿，尚未傳送",
    );
  }
  A.registerAction("crm-open", (el) =>
    open(el.dataset.caseId, el.dataset.serviceOrderId),
  );
  A.registerAction("crm-customer-form", profile);
  A.registerAction("crm-link-form", link);
  A.registerAction("crm-link-search", async (el) => {
    const form = el.closest("form"),
      op = form.assistanceOperation,
      privacy = window.TravelPrivacy.capture();
    const { customers } = await A.api(
      `/api/mom/customers?q=${encodeURIComponent(form.elements.customer_query.value)}`,
    );
    if (
      !form.isConnected ||
      !A.sheetRequestCurrent(op.stamp) ||
      !window.TravelPrivacy.current(privacy)
    )
      return;
    const select = form.elements.customer_id;
    select.replaceChildren(
      ...customers.map(
        (value) =>
          new Option(`${value.display_name} · ${value.id.slice(-6)}`, value.id),
      ),
    );
    if (!customers.length)
      select.append(new Option("找不到客戶，請修改關鍵字或建立新客戶", ""));
  });
  A.registerAction("crm-consent-form", consent);
  A.registerAction("crm-message-form", messageForm);
  A.registerAction("crm-reveal", reveal);
  A.registerAction("crm-message-attest", attest);
  A.registerAction("crm-customer-history", history);
  A.registerAction("crm-message-copy", async () => {
    await navigator.clipboard.writeText($("#crmMessageBody").value);
    A.showToast("已複製，尚未傳送；修改文字需另存才會保留。");
  });
  A.registerAction("crm-save-reply", saveReply);
  A.registerAction("crm-draft-history", (el) => open(el.dataset.caseId));
  [
    "customerProfileForm",
    "customerLinkForm",
    "customerConsentForm",
    "communicationForm",
    "communicationAttestForm",
    "replySaveForm",
  ].forEach((id) => A.registerForm(id, submit));
})();

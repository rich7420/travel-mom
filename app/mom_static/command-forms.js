"use strict";
// Shared private command recovery: frozen memory payload, owned UUID, metadata receipts.
(() => {
  const A = window.MomApp,
    P = window.TravelPrivacy,
    E = A.escapeHtml;
  const base = (c) => `/api/mom/cases/${encodeURIComponent(c)}`;
  const key = (scope, customer) =>
    `${customer ? "travel-customer" : "travel-assistance"}-intents:${scope}`;
  function pending(scope, customer = false) {
    try {
      const items = JSON.parse(
        sessionStorage.getItem(key(scope, customer)) || "[]",
      );
      return Array.isArray(items) ? items : [];
    } catch {
      return [];
    }
  }
  function put(scope, customer, item) {
    const items = pending(scope, customer).filter(
      (v) => v.request_id !== item.request_id,
    );
    items.push(item);
    sessionStorage.setItem(key(scope, customer), JSON.stringify(items));
  }
  function forget(scope, customer, id) {
    const items = pending(scope, customer).filter((v) => v.request_id !== id);
    if (items.length)
      sessionStorage.setItem(key(scope, customer), JSON.stringify(items));
    else sessionStorage.removeItem(key(scope, customer));
  }
  const headers = (actor) => ({
    "X-Travel-Service-Actor": encodeURIComponent(actor),
  });
  function assertActor(actor) {
    if (actor !== A.getActor())
      throw new Error("操作帳號已變更，請用原帳號核對上次結果。");
  }
  async function receipt(scope, customer, id, actor) {
    const path = customer
      ? `/api/mom/customer-receipts/${encodeURIComponent(scope)}/${id}`
      : `${base(scope)}/assistance-receipts/${id}`;
    const result = await A.api(path, { headers: headers(actor) });
    assertActor(actor);
    return result;
  }
  async function recover(scope, customer = false) {
    const actor = A.getActor();
    let text = "";
    for (const item of pending(scope, customer)) {
      try {
        const found = await receipt(scope, customer, item.request_id, actor);
        if (found.committed) {
          forget(scope, customer, item.request_id);
          text = "已核對上次儲存成功，沒有重複新增。";
        } else if (item.actor === actor)
          text =
            "上次操作尚未查到保存紀錄。請核對後重新填寫；上次編號保留供查詢。";
        else text = "此裝置有其他帳號的待確認操作，請用原帳號核對。";
      } catch (err) {
        if (err.status === 409)
          text = "此裝置有其他帳號的待確認操作，請用原帳號核對。";
        else throw err;
      }
    }
    return text ? `<p class="notice-card" role="status">${E(text)}</p>` : "";
  }
  function freeze(form) {
    form.dataset.uncertain = "true";
    form.querySelectorAll("input,textarea,select").forEach((el) => {
      el.disabled = true;
    });
    if (!form.querySelector("[data-action=assistance-reconcile]"))
      form.insertAdjacentHTML(
        "beforeend",
        '<button type="button" class="secondary-button full" data-action="assistance-reconcile">核對上次保存結果</button>',
      );
  }
  async function submit(form, data, op) {
    const command =
      form.assistanceCommand ||
      (form.assistanceCommand = {
        actor: op.actor || A.getActor(),
        scope: op.scope,
        customer: !!op.customer,
      });
    assertActor(command.actor);
    // Resolve identity before sending any mutable form content; the server checks it again.
    const auth = await A.api("/api/auth/session");
    assertActor(command.actor);
    if ((auth.email || "operator") !== command.actor) {
      P.scrub();
      throw new Error("登入帳號已變更，請返回核對上次結果。");
    }
    if (command.frozen) {
      const found = await receipt(
        command.scope,
        command.customer,
        command.requestId,
        command.actor,
      );
      if (found.committed) {
        forget(command.scope, command.customer, command.requestId);
        return found;
      }
    } else {
      const previous = pending(command.scope, command.customer).find(
        (item) =>
          item.actor === command.actor &&
          item.action === op.action &&
          item.target_id === (op.target || null),
      );
      command.requestId = previous?.request_id || crypto.randomUUID();
      command.frozen = { ...data, request_id: command.requestId };
      if (previous) {
        const found = await receipt(
          command.scope,
          command.customer,
          command.requestId,
          command.actor,
        );
        if (found.committed) {
          forget(command.scope, command.customer, command.requestId);
          op.recovered = true;
          return found;
        }
      }
      put(command.scope, command.customer, {
        request_id: command.requestId,
        actor: command.actor,
        action: op.action,
        target_id: op.target || null,
      });
    }
    const submitted = JSON.stringify(command.frozen);
    try {
      const result = await A.api(op.endpoint, {
        method: op.method || "POST",
        headers: headers(command.actor),
        body: submitted,
      });
      assertActor(command.actor);
      forget(command.scope, command.customer, command.requestId);
      return result;
    } catch (err) {
      if (err.status === 401 || err.status === 412) {
        P.scrub();
        freeze(form);
        throw err;
      }
      if (err.status >= 400 && err.status < 500) {
        try {
          const found = await receipt(
            command.scope,
            command.customer,
            command.requestId,
            command.actor,
          );
          if (found.committed) {
            forget(command.scope, command.customer, command.requestId);
            return found;
          }
          forget(command.scope, command.customer, command.requestId);
          command.frozen = null;
        } catch (receiptError) {
          freeze(form);
          throw receiptError;
        }
      } else freeze(form);
      throw err;
    }
  }
  function context(preservedEditor = null) {
    const generation = A.beginSheetRequest(preservedEditor);
    return generation === null ? null : { generation, privacy: P.capture() };
  }
  const current = (ctx) =>
    ctx && A.sheetRequestCurrent(ctx.generation) && P.current(ctx.privacy);
  const proof = () =>
    A.field(
      "核對依據（通知或對話編號）",
      "reference",
      "",
      'required maxlength="500"',
    ) +
    A.field(
      "實際時間（裝置時區）",
      "occurred_at",
      A.localDateTime(),
      'type="datetime-local" required',
    ) +
    '<label class="checkbox-pill"><input type="checkbox" name="checked" required>我已核對内容與依據。</label>';
  const evidence = (v) => ({
    reference: v.reference,
    occurred_at: new Date(v.occurred_at).toISOString(),
    checked: v.checked === "on",
  });
  function mount(ctx, c, title, formId, body, op, back, label = "保存紀錄") {
    if (!current(ctx)) return;
    if (
      !A.openSheet(
        title,
        `<form id="${formId}" class="form-grid" data-private>${body}${proof()}<button type="submit" class="primary-button full">${E(label)}</button></form>`,
        true,
        "reply",
        c,
        ctx.generation,
      )
    )
      return;
    const form = document.getElementById(formId);
    form.assistanceOperation = {
      ...op,
      actor: ctx.privacy.actor,
      back,
      stamp: A.currentSheetGeneration(),
    };
    A.setSheetBack(back, "返回");
  }
  async function saved(form, text) {
    const op = form.assistanceOperation;
    if (form.assistanceCommand) form.assistanceCommand.frozen = null;
    op.draftBody = null;
    A.markFormCommitted(form, op.returnAction || "crm-open", {
      caseId: op.caseId || op.scope,
      id: op.returnId || "",
    });
    form.dataset.dirty = "false";
    form.querySelectorAll("input,textarea,select").forEach((el) => {
      el.value = "";
    });
    A.showToast(
      op.recovered ? "已核對上次保存成功，請重新核對本次內容。" : text,
    );
    if (form.isConnected && A.sheetRequestCurrent(op.stamp)) await op.back();
  }
  const text = (label, name, value = "", max = 8000) =>
    `<label><span>${E(label)}</span><textarea name="${name}" rows="5" maxlength="${max}" required>${E(value)}</textarea></label>`;
  const select = (label, name, options, value = "") =>
    `<label><span>${E(label)}</span><select name="${name}" required>${Object.entries(
      options,
    )
      .map(
        ([k, v]) =>
          `<option value="${E(k)}" ${k === value ? "selected" : ""}>${E(v)}</option>`,
      )
      .join("")}</select></label>`;
  const button = (label, action, c, id = "", extra = "") =>
    `<button type="button" class="secondary-button" data-action="${action}" data-case-id="${E(c)}" data-id="${E(id)}" ${extra}>${E(label)}</button>`;
  A.registerAction("assistance-reconcile", async (el) => {
    const form = el.closest("form"),
      command = form.assistanceCommand,
      op = form.assistanceOperation;
    if (!command?.requestId)
      throw new Error("請回到列表，以原帳號核對待確認紀錄。");
    const found = await receipt(
      command.scope,
      command.customer,
      command.requestId,
      command.actor,
    );
    if (found.committed) {
      forget(command.scope, command.customer, command.requestId);
      await saved(form, "已核對上次保存成功，沒有重複新增。");
    } else {
      if (!command.frozen) {
        A.showToast(
          "已確認尚未保存，私密內容已清除。請返回列表重新填寫，沿用原編號核對。",
        );
        return;
      }
      form.dataset.uncertain = "false";
      const submit = form.querySelector("button[type=submit]");
      submit.disabled = false;
      submit.textContent = "以原內容重試保存";
      A.showToast("已確認尚未保存，可以用原內容重試。");
    }
  });
  window.Assistance = Object.freeze({
    base,
    context,
    current,
    mount,
    proof,
    evidence,
    submit,
    saved,
    recover,
    text,
    select,
    button,
    headers,
  });
})();

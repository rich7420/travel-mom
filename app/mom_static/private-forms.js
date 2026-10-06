"use strict";
// One epoch owns every private surface. Storage contains no private form content.
(() => {
  const A = window.MomApp;
  let epoch = 0;
  function scrub() {
    ++epoch;
    document.querySelectorAll("[data-private]").forEach((node) => {
      node.querySelectorAll("input,textarea,select").forEach((input) => {
        input.value = "";
      });
      const command = node.assistanceCommand,
        op = node.assistanceOperation;
      if (command) command.frozen = null;
      if (op) op.draftBody = null;
      node.replaceChildren();
      node.dataset.dirty = "false";
      if (command?.requestId) {
        node.dataset.uncertain = "true";
        node.insertAdjacentHTML(
          "beforeend",
          '<p class="notice-card warn">登入或帳號已變更，私密內容已清除。請以原帳號核對上次保存結果。</p><button type="button" class="secondary-button full" data-action="assistance-reconcile">核對上次保存結果</button>',
        );
      }
      if (op)
        node.insertAdjacentHTML(
          "beforeend",
          `<button type="button" class="secondary-button full" data-action="${A.escapeHtml(op.returnAction || "crm-open")}" data-case-id="${A.escapeHtml(op.caseId || op.scope)}" data-id="${A.escapeHtml(op.returnId || "")}">返回列表重新核對</button>`,
        );
    });
  }
  window.addEventListener("travel-auth-expired", scrub);
  window.addEventListener("travel-actor-changed", scrub);
  document.querySelector("#sheet").addEventListener("close", scrub);
  window.TravelPrivacy = Object.freeze({
    capture: () => ({ epoch, actor: A.getActor() }),
    current: (token) => token.epoch === epoch && token.actor === A.getActor(),
    scrub,
  });
})();

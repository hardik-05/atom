// Two-step sign-in. A file rather than an inline <script>: the Content-Security-
// Policy allows scripts from this origin only.
//
// Step 1 posts the username and password; the server answers with a short-lived
// pending cookie. Step 2 posts the authenticator code against that cookie and,
// on success, the server sets the session — after which "/" serves the console.
(function () {
  "use strict";

  var passwordStep = document.getElementById("password-step");
  var codeStep = document.getElementById("code-step");
  var codeInput = document.getElementById("code");

  function post(path, body) {
    return fetch("/api/auth/" + path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Atom-Request": "1",
      },
      body: JSON.stringify(body),
    }).then(function (response) {
      return response
        .json()
        .catch(function () {
          return {};
        })
        .then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
    });
  }

  function errorOf(form) {
    return form.querySelector(".error");
  }

  function busy(form, on) {
    var button = form.querySelector("button[type=submit]");
    button.disabled = on;
  }

  function showPasswordStep(message) {
    codeStep.hidden = true;
    passwordStep.hidden = false;
    passwordStep.reset();
    errorOf(passwordStep).textContent = message || "";
    document.getElementById("username").focus();
  }

  function showCodeStep() {
    passwordStep.hidden = true;
    codeStep.hidden = false;
    codeStep.reset();
    errorOf(codeStep).textContent = "";
    codeInput.focus();
  }

  function failure(result) {
    if (result.data && result.data.error) return result.data.error;
    return "Sign-in failed (" + result.status + ").";
  }

  passwordStep.addEventListener("submit", function (event) {
    event.preventDefault();
    var username = passwordStep.username.value.trim();
    var password = passwordStep.password.value;
    if (!username || !password) {
      errorOf(passwordStep).textContent = "Enter your username and password.";
      return;
    }
    busy(passwordStep, true);
    errorOf(passwordStep).textContent = "";
    post("password", { username: username, password: password })
      .then(function (result) {
        if (result.ok) {
          showCodeStep();
        } else {
          passwordStep.password.value = "";
          errorOf(passwordStep).textContent = failure(result);
        }
      })
      .catch(function () {
        errorOf(passwordStep).textContent = "Could not reach the server. Try again.";
      })
      .then(function () {
        busy(passwordStep, false);
      });
  });

  codeInput.addEventListener("input", function () {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
  });

  codeStep.addEventListener("submit", function (event) {
    event.preventDefault();
    var code = codeInput.value;
    if (!/^\d{6}$/.test(code)) {
      errorOf(codeStep).textContent = "Enter the 6-digit code.";
      return;
    }
    busy(codeStep, true);
    errorOf(codeStep).textContent = "";
    post("totp", { totp: code })
      .then(function (result) {
        if (result.ok) {
          // The session cookie is set; the server now serves the console here.
          window.location.replace("/");
          return;
        }
        if (result.data && result.data.restart) {
          showPasswordStep(result.data.error);
          return;
        }
        codeInput.value = "";
        errorOf(codeStep).textContent = failure(result);
        codeInput.focus();
      })
      .catch(function () {
        errorOf(codeStep).textContent = "Could not reach the server. Try again.";
      })
      .then(function () {
        busy(codeStep, false);
      });
  });

  document.getElementById("restart").addEventListener("click", function () {
    showPasswordStep("");
  });
})();

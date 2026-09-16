(() => {
  const tabs = document.querySelectorAll(".auth-tab");
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  let selectedRole = "recruiter";

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.toggle("is-active", t === tab));
      const isLogin = tab.dataset.tab === "login";
      loginForm.hidden = !isLogin;
      registerForm.hidden = isLogin;
    });
  });

  document.querySelectorAll(".role-option").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".role-option").forEach(b => b.classList.toggle("is-active", b === btn));
      selectedRole = btn.dataset.role;
    });
  });

  loginForm.addEventListener("submit", async e => {
    e.preventDefault();
    const status = document.getElementById("login-status");
    status.textContent = "";
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("login-email").value,
          password: document.getElementById("login-password").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't sign in.");
      window.location.href = data.redirect;
    } catch (err) {
      status.textContent = err.message;
    }
  });

  registerForm.addEventListener("submit", async e => {
    e.preventDefault();
    const status = document.getElementById("register-status");
    status.textContent = "";
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: document.getElementById("register-name").value,
          email: document.getElementById("register-email").value,
          password: document.getElementById("register-password").value,
          role: selectedRole,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't create that account.");
      window.location.href = data.redirect;
    } catch (err) {
      status.textContent = err.message;
    }
  });
})();

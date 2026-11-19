const form = document.querySelector("#login-form");
const errorMessage = document.querySelector("#login-error");
const submitButton = form.querySelector('button[type="submit"]');

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorMessage.hidden = true;
  submitButton.disabled = true;

  const formData = new FormData(form);
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: formData.get("username"),
        password: formData.get("password"),
      }),
    });
    if (!response.ok) {
      errorMessage.textContent =
        response.status === 401
          ? "Invalid username or password."
          : "Sign-in failed. Please try again.";
      errorMessage.hidden = false;
      return;
    }
    window.location.assign("/dashboard");
  } catch {
    errorMessage.textContent = "Could not reach the server. Please try again.";
    errorMessage.hidden = false;
  } finally {
    submitButton.disabled = false;
  }
});

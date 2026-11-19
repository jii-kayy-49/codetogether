const welcomeUser = document.querySelector("#welcome-user");
const memberList = document.querySelector("#member-list");
const logoutButton = document.querySelector("#logout-button");

function renderMembers(users, currentUsername) {
  memberList.replaceChildren();
  for (const username of users) {
    const card = document.createElement("article");
    card.className = "member-card";

    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = username.slice(0, 1);

    const details = document.createElement("div");
    details.className = "member-details";

    const name = document.createElement("p");
    name.className = "member-name";
    name.textContent = username;

    const caption = document.createElement("p");
    caption.className = "member-caption";
    caption.textContent = username === currentUsername ? "You · Member" : "Member";

    details.append(name, caption);
    card.append(avatar, details);
    memberList.append(card);
  }
}

async function loadDashboard() {
  const response = await fetch("/api/session");
  if (response.status === 401) {
    window.location.replace("/");
    return;
  }
  if (!response.ok) {
    throw new Error("Could not load the current session.");
  }

  const session = await response.json();
  welcomeUser.textContent = `Signed in as ${session.username}`;
  renderMembers(session.users, session.username);
}

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    if (!response.ok) {
      throw new Error("Sign-out failed.");
    }
    window.location.assign("/");
  } catch {
    logoutButton.disabled = false;
    window.alert("Could not sign out. Please try again.");
  }
});

loadDashboard().catch(() => {
  memberList.textContent = "Could not load the team. Please refresh the page.";
});

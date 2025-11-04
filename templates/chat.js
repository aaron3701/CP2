// Import Firebase SDK
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {
  getFirestore,
  collection,
  addDoc,
  onSnapshot,
  query,
  orderBy
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";

// Your Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyBO0DJJlQGvkHmg0MkjdHYXc7nUK-SOSEc",
  authDomain: "juliaai-8bc2c.firebaseapp.com",
  projectId: "juliaai-8bc2c",
  storageBucket: "juliaai-8bc2c.firebasestorage.app",
  messagingSenderId: "84764870175",
  appId: "1:84764870175:web:0631e73965147023c7f72a"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

// HTML elements
const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

// Keep track of rendered message IDs so we don't duplicate
const shownMessages = new Set();
const shownReplies = new Set();

// Helper: create bubble element
function createBubble(text, who /* "user" or "assistant" */) {
  const wrapper = document.createElement("div");
  wrapper.classList.add("message-row");
  wrapper.classList.add(who === "user" ? "user" : "julia");
  const bubble = document.createElement("div");
  bubble.classList.add("message-bubble");
  bubble.classList.add(who === "user" ? "user-bubble" : "julia-bubble");

  // optionally allow simple HTML (escape user input if needed)
  const p = document.createElement("p");
  p.textContent = text;
  bubble.appendChild(p);
  wrapper.appendChild(bubble);
  return wrapper;
}

// Append and scroll
function appendAndScroll(node) {
  chatBox.appendChild(node);
  chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: "smooth" });
}

// Firestore references + query
const messagesRef = collection(db, "messages");
const q = query(messagesRef, orderBy("timestamp"));

// Listen for changes and append only diffs
onSnapshot(q, (snapshot) => {
  snapshot.docChanges().forEach((change) => {
    const id = change.doc.id;
    const data = change.doc.data() || {};

    // When a new message doc is created (user message)
    if (change.type === "added") {
      // Only show once
      if (shownMessages.has(id)) return;
      shownMessages.add(id);

      // Render user bubble (display text field)
      const text = data.text || "";
      const role = (data.role || "").toLowerCase();
      if (role === "user") {
        const userBubble = createBubble(text, "user");
        // attach a data attribute so we can relate reply later if needed
        userBubble.dataset.msgId = id;
        appendAndScroll(userBubble);
      } else if (role === "assistant" && (data.reply || data.text)) {
        // If an assistant message was directly written
        const assText = data.reply || data.text;
        const juliaBubble = createBubble(assText, "assistant");
        appendAndScroll(juliaBubble);
        shownReplies.add(id);
      }
    }

    // When a doc is modified (status updated => reply written)
    if (change.type === "modified") {
      // If it now has status === 'replied' and reply exists, append assistant bubble
      const status = (data.status || "").toLowerCase();
      if (status === "replied" && data.reply) {
        // Avoid showing duplicate reply
        if (shownReplies.has(id)) return;
        shownReplies.add(id);

        const replyBubble = createBubble(data.reply, "assistant");
        // Optionally: insert reply bubble right after the user message bubble
        // Try to locate user bubble by data-msgId
        const userBubbleRow = Array.from(chatBox.children).find(
          (row) => row.dataset && row.dataset.msgId === id
        );
        if (userBubbleRow) {
          // insert after the user message
          userBubbleRow.insertAdjacentElement("afterend", replyBubble);
          // ensure scroll
          chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: "smooth" });
        } else {
          // fallback: just append
          appendAndScroll(replyBubble);
        }
      }
    }
  });
});

// Send message (button)
sendBtn.onclick = async () => {
  const text = userInput.value.trim();
  if (!text) return;
  try {
    await addDoc(messagesRef, {
      text,
      role: "user",
      status: "pending",
      timestamp: new Date()
    });
    userInput.value = "";
  } catch (e) {
    console.error("Failed to send message:", e);
  }
};

// Allow Enter key to send
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});

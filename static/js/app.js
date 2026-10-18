/**
 * KnowOps AI — Frontend Application Logic
 * Phase 2.5: User API, JWT Authentication, Multi-turn Chat, and Grounded Citations
 */

(function () {
  'use strict';

  // State
  let activeConversationId = null;
  let jwtToken = localStorage.getItem('knowops_jwt') || null;
  let currentUser = null;

  // DOM Elements
  const elMessagesFeed     = document.getElementById('messages-feed');
  const elHeroWelcome      = document.getElementById('hero-welcome');
  const elQueryForm        = document.getElementById('query-form');
  const elInputQuestion    = document.getElementById('input-question');
  const elBtnSend          = document.getElementById('btn-send-query');
  const elSelectTopK       = document.getElementById('select-top-k');
  const elThreadBadge      = document.getElementById('thread-badge');
  const elBtnNewConv       = document.getElementById('btn-new-conversation');
  const elBtnClearChat     = document.getElementById('btn-clear-chat');
  const elSessionList      = document.getElementById('session-list');

  // Status & Health Elements
  const elPillDb           = document.getElementById('pill-db-status');
  const elStatDocs         = document.getElementById('stat-docs');
  const elStatChunks       = document.getElementById('stat-chunks');

  // Auth Elements
  const elBtnAuthToggle    = document.getElementById('btn-auth-toggle');
  const elAuthBtnLabel     = document.getElementById('auth-btn-label');
  const elModalLogin       = document.getElementById('modal-login');
  const elBtnCloseLogin    = document.getElementById('btn-close-login');
  const elBtnCancelLogin   = document.getElementById('btn-cancel-login');
  const elFormLogin        = document.getElementById('form-login');
  const elInputUsername    = document.getElementById('input-username');
  const elInputPassword    = document.getElementById('input-password');
  const elLoginErrorMsg    = document.getElementById('login-error-msg');
  const elUserNameDisplay  = document.getElementById('user-name-display');
  const elUserRoleDisplay  = document.getElementById('user-role-display');
  const elUserAvatar       = document.getElementById('user-avatar');

  // Diagnostics Elements
  const elBtnDiagnostics   = document.getElementById('btn-diagnostics');
  const elModalDiagnostics = document.getElementById('modal-diagnostics');
  const elBtnCloseDiag     = document.getElementById('btn-close-diag');
  const elBtnRefreshDiag   = document.getElementById('btn-refresh-diag');
  const elDiagDbVal        = document.getElementById('diag-db-val');
  const elDiagDocsVal      = document.getElementById('diag-docs-val');
  const elDiagChunksVal    = document.getElementById('diag-chunks-val');
  const elDiagJwtVal       = document.getElementById('diag-jwt-val');

  // ---------------------------------------------------------------------------
  // Boot & Initialization
  // ---------------------------------------------------------------------------
  async function init() {
    setupEventListeners();
    await checkHealth();
    await restoreAuthSession();
    await loadRecentConversations();
  }

  // Phase 5.4: every API route except /health and /auth/login now requires a JWT.
  // Build headers for a fetch call; pass withJson=true to also set Content-Type.
  function authHeaders(withJson) {
    const headers = {};
    if (withJson) headers['Content-Type'] = 'application/json';
    if (jwtToken) headers['Authorization'] = `Bearer ${jwtToken}`;
    return headers;
  }

  // ---------------------------------------------------------------------------
  // Health & Diagnostics
  // ---------------------------------------------------------------------------
  async function checkHealth() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        elPillDb.classList.add('status-healthy');
        elStatDocs.textContent = data.knowledge_base.documents || 4;
        elStatChunks.textContent = data.knowledge_base.chunks || 61;
        
        elDiagDbVal.textContent = 'CONNECTED (Neon)';
        elDiagDbVal.style.color = '#34d399';
        elDiagDocsVal.textContent = data.knowledge_base.documents;
        elDiagChunksVal.textContent = data.knowledge_base.chunks;
      } else {
        elPillDb.classList.remove('status-healthy');
        elDiagDbVal.textContent = 'DEGRADED';
        elDiagDbVal.style.color = '#f87171';
      }
    } catch (err) {
      console.warn('Health check failed:', err);
      elPillDb.classList.remove('status-healthy');
      elDiagDbVal.textContent = 'UNREACHABLE';
      elDiagDbVal.style.color = '#f87171';
    }

    elDiagJwtVal.textContent = jwtToken ? 'Valid Active JWT' : 'None (Guest Mode)';
  }

  // ---------------------------------------------------------------------------
  // Authentication
  // ---------------------------------------------------------------------------
  async function restoreAuthSession() {
    if (!jwtToken) {
      updateAuthUI(null);
      return;
    }

    try {
      const res = await fetch('/auth/me', {
        headers: { 'Authorization': `Bearer ${jwtToken}` }
      });
      if (res.ok) {
        currentUser = await res.json();
        updateAuthUI(currentUser);
      } else {
        // Token expired or invalid
        logout();
      }
    } catch (err) {
      console.warn('Session restoration failed:', err);
      logout();
    }
  }

  function updateAuthUI(user) {
    if (user) {
      elAuthBtnLabel.textContent = 'Sign Out';
      elBtnAuthToggle.classList.remove('btn-primary');
      elBtnAuthToggle.classList.add('btn-secondary');
      elUserNameDisplay.textContent = user.username;
      elUserRoleDisplay.textContent = 'SRE / Incident Operator';
      elUserAvatar.textContent = user.username.slice(0, 2).toUpperCase();
      elUserAvatar.style.background = 'linear-gradient(135deg, #10b981, #059669)';
    } else {
      elAuthBtnLabel.textContent = 'Sign In';
      elBtnAuthToggle.classList.add('btn-primary');
      elBtnAuthToggle.classList.remove('btn-secondary');
      elUserNameDisplay.textContent = 'Guest Operator';
      elUserRoleDisplay.textContent = 'Read-Only Mode';
      elUserAvatar.textContent = 'OP';
      elUserAvatar.style.background = 'linear-gradient(135deg, #3b82f6, #1d4ed8)';
    }
    elDiagJwtVal.textContent = jwtToken ? 'Active Operator JWT' : 'None (Guest Mode)';
  }

  async function handleLoginSubmit(e) {
    e.preventDefault();
    elLoginErrorMsg.classList.add('hidden');
    const username = elInputUsername.value.trim();
    const password = elInputPassword.value.trim();

    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || 'Login failed');
      }

      const data = await res.json();
      jwtToken = data.access_token;
      localStorage.setItem('knowops_jwt', jwtToken);
      currentUser = { username: data.username, role: 'operator' };
      updateAuthUI(currentUser);
      elModalLogin.classList.add('hidden');
      elFormLogin.reset();
      loadRecentConversations();
    } catch (err) {
      elLoginErrorMsg.textContent = err.message;
      elLoginErrorMsg.classList.remove('hidden');
    }
  }

  function logout() {
    jwtToken = null;
    currentUser = null;
    localStorage.removeItem('knowops_jwt');
    updateAuthUI(null);
    elSessionList.innerHTML = '';
    activeConversationId = null;
  }

  // ---------------------------------------------------------------------------
  // Conversation Sessions (Multi-Turn)
  // ---------------------------------------------------------------------------
  async function loadRecentConversations() {
    if (!jwtToken) {
      elSessionList.innerHTML = '';
      return;
    }
    try {
      const res = await fetch('/conversations?limit=15', { headers: authHeaders() });
      if (res.ok) {
        const conversations = await res.json();
        renderSessionList(conversations);
      }
    } catch (err) {
      console.warn('Failed to load conversations:', err);
    }
  }

  function renderSessionList(conversations) {
    elSessionList.innerHTML = '';
    
    // Always include a "+ Current Active" if no ID
    const currentItem = document.createElement('div');
    currentItem.className = `session-item ${activeConversationId === null ? 'active' : ''}`;
    currentItem.innerHTML = `
      <span class="session-icon">💬</span>
      <div class="session-text">${activeConversationId ? 'New Incident' : 'Active Session'}</div>
    `;
    currentItem.onclick = () => startNewConversation();
    elSessionList.appendChild(currentItem);

    conversations.forEach(c => {
      const item = document.createElement('div');
      item.className = `session-item ${activeConversationId === c.id ? 'active' : ''}`;
      item.id = `session-item-${c.id}`;
      item.innerHTML = `
        <span class="session-icon">📁</span>
        <div class="session-text">Session #${c.id} (${c.message_count || 0})</div>
      `;
      item.onclick = () => switchConversation(c.id);
      elSessionList.appendChild(item);
    });
  }

  async function startNewConversation() {
    activeConversationId = null;
    elThreadBadge.textContent = 'Session #New';
    elMessagesFeed.innerHTML = '';
    elMessagesFeed.appendChild(elHeroWelcome);
    elHeroWelcome.style.display = 'flex';
    loadRecentConversations();
  }

  async function switchConversation(id) {
    activeConversationId = id;
    elThreadBadge.textContent = `Session #${id}`;
    elMessagesFeed.innerHTML = '';
    elHeroWelcome.style.display = 'none';

    try {
      const res = await fetch(`/conversations/${id}`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        data.messages.forEach(msg => {
          if (msg.role === 'user') {
            appendUserMessage(msg.content);
          } else {
            appendModelMessage(msg.content, []);
          }
        });
      }
    } catch (err) {
      console.error('Failed to load conversation history:', err);
    }

    loadRecentConversations();
  }

  // ---------------------------------------------------------------------------
  // Chat & Q&A (/ask Endpoint)
  // ---------------------------------------------------------------------------
  async function submitQuery(queryText) {
    if (!queryText || !queryText.trim()) return;

    // Phase 5.4: /ask now requires a signed-in operator.
    if (!jwtToken) {
      elModalLogin.classList.remove('hidden');
      return;
    }

    // Hide hero welcome
    if (elHeroWelcome) {
      elHeroWelcome.style.display = 'none';
    }

    // Append User Message Bubble
    appendUserMessage(queryText);

    // Disable inputs & show typing indicator
    elBtnSend.disabled = true;
    elInputQuestion.value = '';
    const typingRow = appendTypingIndicator();
    elMessagesFeed.scrollTop = elMessagesFeed.scrollHeight;

    const topK = parseInt(elSelectTopK.value, 10) || 5;

    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          question: queryText,
          conversation_id: activeConversationId,
          top_k: topK
        })
      });

      // Remove typing indicator
      typingRow.remove();

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || `Server error (${res.status})`);
      }

      const data = await res.json();

      // Update active conversation ID if newly created
      if (data.conversation_id && activeConversationId !== data.conversation_id) {
        activeConversationId = data.conversation_id;
        elThreadBadge.textContent = `Session #${activeConversationId}`;
        loadRecentConversations();
      }

      // Render Assistant reply with citations
      appendModelMessage(data.answer, data.sources || []);

    } catch (err) {
      typingRow.remove();
      appendErrorMessage(err.message);
    } finally {
      elBtnSend.disabled = false;
      elMessagesFeed.scrollTop = elMessagesFeed.scrollHeight;
    }
  }

  function appendUserMessage(text) {
    const row = document.createElement('div');
    row.className = 'msg-row user';
    row.innerHTML = `
      <div class="msg-avatar">OP</div>
      <div class="msg-content">
        <div class="msg-bubble">${escapeHtml(text)}</div>
      </div>
    `;
    elMessagesFeed.appendChild(row);
    elMessagesFeed.scrollTop = elMessagesFeed.scrollHeight;
  }

  function appendTypingIndicator() {
    const row = document.createElement('div');
    row.className = 'msg-row model';
    row.innerHTML = `
      <div class="msg-avatar">⚡</div>
      <div class="msg-content">
        <div class="msg-bubble typing-bubble">
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
        </div>
      </div>
    `;
    elMessagesFeed.appendChild(row);
    return row;
  }

  function appendModelMessage(answerText, sources) {
    const row = document.createElement('div');
    row.className = 'msg-row model';

    // Format markdown codeblocks and formatting
    const formattedHtml = formatMarkdown(answerText);

    let citationsHtml = '';
    if (sources && sources.length > 0) {
      const cardsHtml = sources.map(s => {
        const pct = Math.round(s.similarity * 100);
        return `
          <div class="citation-card" title="${escapeHtml(s.content)}">
            <span class="sim-pill">${pct}% Match</span>
            <span class="citation-title">${escapeHtml(s.document_title)} &rsaquo; ${escapeHtml(s.heading || 'Section')}</span>
          </div>
        `;
      }).join('');

      citationsHtml = `
        <div class="citations-tray">
          <div class="citations-header">
            <span>📚 Grounded Sources (${sources.length} citations)</span>
          </div>
          <div class="citation-cards">
            ${cardsHtml}
          </div>
        </div>
      `;
    }

    row.innerHTML = `
      <div class="msg-avatar">⚡</div>
      <div class="msg-content">
        <div class="msg-bubble">
          ${formattedHtml}
          ${citationsHtml}
        </div>
      </div>
    `;

    elMessagesFeed.appendChild(row);

    // Bind copy-code buttons
    row.querySelectorAll('.copy-code-btn').forEach(btn => {
      btn.onclick = () => {
        const code = btn.nextElementSibling.innerText;
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = 'Copied!';
          setTimeout(() => btn.textContent = 'Copy', 1500);
        });
      };
    });

    elMessagesFeed.scrollTop = elMessagesFeed.scrollHeight;
  }

  function appendErrorMessage(errorMsg) {
    const row = document.createElement('div');
    row.className = 'msg-row model';
    row.innerHTML = `
      <div class="msg-avatar" style="background:#ef4444;">⚠️</div>
      <div class="msg-content">
        <div class="msg-bubble" style="border-color:#ef4444; color:#fca5a5;">
          <strong>Error encountered:</strong> ${escapeHtml(errorMsg)}
        </div>
      </div>
    `;
    elMessagesFeed.appendChild(row);
  }

  // ---------------------------------------------------------------------------
  // Markdown & Text Helpers
  // ---------------------------------------------------------------------------
  function formatMarkdown(text) {
    if (!text) return '';

    // Replace ```bash ... ``` or ``` ... ```
    let parsed = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre><button class="copy-code-btn">Copy</button><code>${escapeHtml(code.trim())}</code></pre>`;
    });

    // Replace inline `code`
    parsed = parsed.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Replace **bold**
    parsed = parsed.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Convert newlines to paragraphs/breaks
    parsed = parsed.split('\n\n').map(p => {
      if (p.startsWith('<pre')) return p;
      return `<p>${p.replace(/\n/g, '<br/>')}</p>`;
    }).join('');

    return parsed;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ---------------------------------------------------------------------------
  // Event Listeners
  // ---------------------------------------------------------------------------
  function setupEventListeners() {
    // Form Submission
    elQueryForm.onsubmit = (e) => {
      e.preventDefault();
      submitQuery(elInputQuestion.value);
    };

    // Textarea Enter key handler
    elInputQuestion.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitQuery(elInputQuestion.value);
      }
    };

    // Prompt Card Clicks
    document.querySelectorAll('.prompt-card, .runbook-item').forEach(el => {
      el.onclick = () => {
        const query = el.getAttribute('data-query');
        if (query) {
          elInputQuestion.value = query;
          submitQuery(query);
        }
      };
    });

    // New Conversation
    elBtnNewConv.onclick = () => startNewConversation();

    // Clear Chat View
    elBtnClearChat.onclick = () => {
      elMessagesFeed.innerHTML = '';
      elMessagesFeed.appendChild(elHeroWelcome);
      elHeroWelcome.style.display = 'flex';
    };

    // Auth Modal Triggers
    elBtnAuthToggle.onclick = () => {
      if (jwtToken) {
        // Sign out
        if (confirm('Sign out from KnowOps operator console?')) {
          logout();
        }
      } else {
        // Open modal
        elModalLogin.classList.remove('hidden');
      }
    };
    elBtnCloseLogin.onclick = () => elModalLogin.classList.add('hidden');
    elBtnCancelLogin.onclick = () => elModalLogin.classList.add('hidden');
    elFormLogin.onsubmit = handleLoginSubmit;

    // Diagnostics Modal Triggers
    elBtnDiagnostics.onclick = () => {
      checkHealth();
      elModalDiagnostics.classList.remove('hidden');
    };
    elBtnCloseDiag.onclick = () => elModalDiagnostics.classList.add('hidden');
    elBtnRefreshDiag.onclick = () => checkHealth();

    // CRM Modal Triggers (Phase 3)
    const elBtnCrmToggle = document.getElementById('btn-crm-toggle');
    const elModalCrm = document.getElementById('modal-crm');
    const elBtnCloseCrm = document.getElementById('btn-close-crm');
    const elBtnToggleNewTicket = document.getElementById('btn-toggle-new-ticket');
    const elBtnCancelCreate = document.getElementById('btn-cancel-create-ticket');
    const elInlineTicketForm = document.getElementById('inline-ticket-form');
    const elFormCreateTicket = document.getElementById('form-create-ticket');
    const elBtnRefreshTickets = document.getElementById('btn-refresh-tickets');

    if (elBtnCrmToggle) {
      elBtnCrmToggle.onclick = () => {
        loadCrmData();
        elModalCrm.classList.remove('hidden');
      };
    }
    if (elBtnCloseCrm) elBtnCloseCrm.onclick = () => elModalCrm.classList.add('hidden');
    if (elBtnToggleNewTicket) {
      elBtnToggleNewTicket.onclick = () => elInlineTicketForm.classList.toggle('hidden');
    }
    if (elBtnCancelCreate) {
      elBtnCancelCreate.onclick = () => elInlineTicketForm.classList.add('hidden');
    }
    if (elBtnRefreshTickets) elBtnRefreshTickets.onclick = () => loadCrmData();
    if (elFormCreateTicket) elFormCreateTicket.onsubmit = handleCreateTicketSubmit;
  }

  // ---------------------------------------------------------------------------
  // CRM & Agent Triage Handlers (Phase 3)
  // ---------------------------------------------------------------------------
  async function loadCrmData() {
    if (!jwtToken) {
      const tbody = document.getElementById('tickets-table-body');
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px;">Sign in to view incident tickets.</td></tr>';
      }
      return;
    }
    try {
      const [resStats, resTickets] = await Promise.all([
        fetch('/tickets/stats', { headers: authHeaders() }),
        fetch('/tickets?limit=50', { headers: authHeaders() })
      ]);

      if (resStats.ok) {
        const stats = await resStats.json();
        document.getElementById('crm-total-tickets').textContent = stats.total_tickets;
        document.getElementById('crm-open-tickets').textContent = stats.open;
        document.getElementById('crm-prog-tickets').textContent = stats.in_progress;
        document.getElementById('crm-res-tickets').textContent = stats.resolved;
        document.getElementById('crm-p1-tickets').textContent = stats.active_p1_incidents;
      }

      if (resTickets.ok) {
        const tickets = await resTickets.json();
        renderTicketsTable(tickets);
      }
    } catch (err) {
      console.warn('Failed to load CRM data:', err);
    }
  }

  function renderTicketsTable(tickets) {
    const tbody = document.getElementById('tickets-table-body');
    if (!tickets || tickets.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px;">No incident tickets recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = tickets.map(t => {
      const pClass = `priority-${t.priority.toLowerCase()}`;
      const sClass = t.status.toLowerCase();
      const isResolved = t.status === 'resolved';

      return `
        <tr id="ticket-row-${t.id}">
          <td><strong>#${t.id}</strong></td>
          <td><span class="priority-pill ${pClass}">${t.priority}</span></td>
          <td>
            <div style="font-weight:600; color:#fff;">${escapeHtml(t.subject)}</div>
            <div style="font-size:11px; color:#94a3b8; max-width:380px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              ${escapeHtml(t.description)}
            </div>
          </td>
          <td><span class="status-tag ${sClass}">${t.status.replace('_', ' ')}</span></td>
          <td>
            ${isResolved 
              ? `<span style="font-size:11px; color:#6ee7b7;">✓ Resolved</span>`
              : `<button class="btn-triage" data-ticket-id="${t.id}">🤖 Auto-Triage</button>`
            }
          </td>
        </tr>
      `;
    }).join('');

    // Bind Auto-Triage buttons
    tbody.querySelectorAll('.btn-triage').forEach(btn => {
      btn.onclick = () => {
        const ticketId = parseInt(btn.getAttribute('data-ticket-id'), 10);
        executeAgentTriage(ticketId, btn);
      };
    });
  }

  async function handleCreateTicketSubmit(e) {
    e.preventDefault();
    if (!jwtToken) {
      alert('Please sign in to create a ticket.');
      return;
    }
    const subject = document.getElementById('new-ticket-subject').value.trim();
    const priority = document.getElementById('new-ticket-priority').value;
    const description = document.getElementById('new-ticket-desc').value.trim();

    try {
      const res = await fetch('/tickets', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ subject, priority, description })
      });

      if (!res.ok) throw new Error('Failed to create ticket');

      document.getElementById('form-create-ticket').reset();
      document.getElementById('inline-ticket-form').classList.add('hidden');
      loadCrmData();
    } catch (err) {
      alert(`Error creating ticket: ${err.message}`);
    }
  }

  async function executeAgentTriage(ticketId, triggerBtn) {
    if (!jwtToken) {
      elModalLogin.classList.remove('hidden');
      return;
    }
    const traceBox = document.getElementById('agent-trace-box');
    const targetSpan = document.getElementById('trace-ticket-target');
    const statusPill = document.getElementById('trace-status-pill');
    const stepsContainer = document.getElementById('agent-trace-steps');
    const summaryBox = document.getElementById('agent-resolution-summary');
    const summaryText = document.getElementById('agent-resolution-text');

    traceBox.classList.remove('hidden');
    targetSpan.textContent = `Ticket #${ticketId}`;
    statusPill.textContent = 'Agent Reasoning (ReAct)...';
    statusPill.style.background = 'rgba(245, 158, 11, 0.2)';
    statusPill.style.color = '#fbbf24';
    stepsContainer.innerHTML = '<div style="font-size:12px; color:#94a3b8; padding:8px;">Running autonomous investigation: lookup_runbook → diagnostics → remediation...</div>';
    summaryBox.classList.add('hidden');

    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.textContent = 'Triaging...';
    }

    try {
      const res = await fetch(`/agent/triage/${ticketId}`, { method: 'POST', headers: authHeaders() });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Triage failed');
      }

      const data = await res.json();

      // Render ReAct trace steps
      stepsContainer.innerHTML = data.triage_trace.map(s => `
        <div class="trace-step-item">
          <div class="step-thought"><strong>Step ${s.step}:</strong> ${escapeHtml(s.thought || '')}</div>
          ${s.action ? `<div class="step-action-tag">⚡ Action: ${escapeHtml(s.action)}(${escapeHtml(JSON.stringify(s.args || {}))})</div>` : ''}
          ${s.observation ? `<div class="step-observation-box">${escapeHtml(s.observation)}</div>` : ''}
        </div>
      `).join('');

      // Render resolution summary
      summaryText.textContent = data.resolution_summary;
      summaryBox.classList.remove('hidden');

      statusPill.textContent = 'Incident Triaged & Resolved';
      statusPill.style.background = 'rgba(16, 185, 129, 0.2)';
      statusPill.style.color = '#6ee7b7';

      // Refresh ticket list to show resolved status
      loadCrmData();

    } catch (err) {
      statusPill.textContent = 'Triage Error';
      statusPill.style.background = 'rgba(239, 68, 68, 0.2)';
      statusPill.style.color = '#f87171';
      stepsContainer.innerHTML = `<div style="color:#f87171; font-size:12px;">Error: ${escapeHtml(err.message)}</div>`;
    } finally {
      if (triggerBtn) triggerBtn.disabled = false;
    }
  }

  // Run on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

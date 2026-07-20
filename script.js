document.addEventListener('DOMContentLoaded', () => {
  // --- UI Elements --- //
  const tableBody = document.getElementById('tableBody');
  const leaderboardList = document.getElementById('leaderboard-list');
  const emptyState = document.getElementById('emptyState');
  const loadingText = document.getElementById('loadingText');
  const loadingSubtext = document.getElementById('loadingSubtext');
  const loadingSpinner = document.getElementById('loadingSpinner');

  const panelLeaderboard = document.getElementById('panel-leaderboard');
  const panelOcs = document.getElementById('panel-ocs');

  const searchInput = document.getElementById('searchInput');
  const dateFrom = document.getElementById('date-from');
  const dateTo = document.getElementById('date-to');
  const reasonFilter = document.getElementById('reason-filter');
  const resultCount = document.getElementById('result-count');

  // --- State --- //
  let allRows = [];     // Raw parsed entries
  let memberMap = {};   // tornId -> { name, tornId, delays: [] }
  let currentTab = 'leaderboard';
  let sortKey = 'exec';  // default sort
  let sortDir = -1;      // -1 for desc, 1 for asc

  // Start data loading immediately
  loadCSV();

  // --- Data Fetching --- //
  async function loadCSV() {
    try {
      // Fetch relative to local workspace/Pages root directory
      const response = await fetch('oc_delays.csv?nocache=' + Date.now());
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const text = await response.text();
      parseCSV(text);
    } catch (error) {
      console.error('Error fetching CSV:', error);
      showErrorState(
        'Failed to Load CSV',
        'Could not fetch "oc_delays.csv". Make sure the file exists and is generated in the repository root.'
      );
    }
  }

  function showErrorState(title, subtext) {
    emptyState.classList.remove('hidden');
    panelLeaderboard.classList.add('hidden');
    panelOcs.classList.add('hidden');
    loadingText.textContent = title;
    loadingSubtext.textContent = subtext;
    loadingSpinner.style.display = 'none';
  }

  // --- Parsing --- //
  function parseCSV(text) {
    const parsed = Papa.parse(text, {
      header: true,
      skipEmptyLines: true
    });

    if (parsed.errors && parsed.errors.length > 0 && (!parsed.data || parsed.data.length === 0)) {
      console.error('PapaParse errors:', parsed.errors);
      showErrorState('Parser Error', 'The CSV file format is empty or malformed.');
      return;
    }

    const data = parsed.data;
    if (data.length === 0) {
      showErrorState('No Delays Logged', 'The delay log file is currently empty.');
      return;
    }

    allRows = [];
    memberMap = {};

    data.forEach(row => {
      // CSV keys: "OC ID", "Expected Ready Time (Timestamp)", "Expected Ready Time (UTC)", "Executed Time (Timestamp)", "Executed Time (UTC)", "Delaying Faction Member(s)"
      const ocId = row["OC ID"] ? row["OC ID"].trim() : '';
      const readyTs = parseInt(row["Expected Ready Time (Timestamp)"], 10);
      const readyUtc = row["Expected Ready Time (UTC)"] ? row["Expected Ready Time (UTC)"].trim() : '';
      const execTs = parseInt(row["Executed Time (Timestamp)"], 10);
      const execUtc = row["Executed Time (UTC)"] ? row["Executed Time (UTC)"].trim() : '';
      const memberStr = row["Delaying Faction Member(s)"] ? row["Delaying Faction Member(s)"].trim() : '';

      if (!ocId || isNaN(readyTs) || isNaN(execTs)) return;

      const delaySeconds = execTs - readyTs;
      const members = parseMembers(memberStr);

      const parsedRow = {
        ocId,
        readyTs,
        readyUtc,
        execTs,
        execUtc,
        delaySeconds,
        members,
        rawMemberStr: memberStr
      };

      allRows.push(parsedRow);

      // Build member map
      members.forEach(m => {
        if (!memberMap[m.tornId]) {
          memberMap[m.tornId] = { name: m.name, tornId: m.tornId, delays: [] };
        }
        memberMap[m.tornId].delays.push({
          ocId,
          date: new Date(execTs * 1000),
          reason: m.reason,
          reasonType: m.reasonType
        });
      });
    });

    // Hide loader
    emptyState.classList.add('hidden');
    
    // Initial display
    updateStats();
    applyFilters();
  }

  function parseMembers(str) {
    if (!str || str.startsWith('None') || str.toLowerCase().includes('leader delay')) return [];
    
    // Split on "; " which divides multiple players
    const parts = splitOnSemicolon(str);
    return parts.map(part => {
      part = part.trim();
      // Format: Name [ID] (Reason details)
      const match = part.match(/^(.+?)\s*\[(\d+)\]\s*\((.+)\)$/);
      if (match) {
        const name = match[1].trim();
        const tornId = match[2];
        const reason = match[3].trim();
        return { name, tornId, reason, reasonType: classifyReason(reason) };
      }
      return { name: part, tornId: '?', reason: '', reasonType: 'other' };
    });
  }

  function splitOnSemicolon(str) {
    const parts = [];
    let depth = 0;
    let cur = '';
    for (let i = 0; i < str.length; i++) {
      const ch = str[i];
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      
      if (ch === ';' && depth === 0) {
        parts.push(cur.trim());
        cur = '';
      } else {
        cur += ch;
      }
    }
    if (cur.trim()) parts.push(cur.trim());
    return parts;
  }

  function classifyReason(reason) {
    const r = reason.toLowerCase();
    if (r.includes('hospital')) return 'hospital';
    if (r.includes('traveling') || r.includes('travelling')) return 'traveling';
    if (r.includes('missing item') || r.includes('missing')) return 'missing';
    return 'other';
  }

  // --- Stats Computation --- //
  function updateStats() {
    const totalOCs = allRows.length;
    const uniqueMembers = Object.keys(memberMap).length;

    let totalDelay = 0;
    let minTs = Infinity;
    let maxTs = 0;

    allRows.forEach(r => {
      totalDelay += r.delaySeconds;
      if (r.execTs < minTs) minTs = r.execTs;
      if (r.execTs > maxTs) maxTs = r.execTs;
    });

    const avgDelay = totalOCs ? Math.round(totalDelay / totalOCs / 60) : 0;

    document.getElementById('stat-total').textContent = totalOCs;
    document.getElementById('stat-members').textContent = uniqueMembers;
    document.getElementById('stat-avg-delay').textContent = avgDelay + ' min';

    if (totalOCs > 0) {
      const fmt = ts => new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
      document.getElementById('stat-date-range').textContent = `${fmt(minTs)} – ${fmt(maxTs)}`;
    } else {
      document.getElementById('stat-date-range').textContent = '—';
    }
  }

  // --- Filtering & Rendering --- //
  window.applyFilters = function() {
    const query = searchInput.value.trim().toLowerCase();
    const fromVal = dateFrom.value;
    const toVal = dateTo.value;
    const reasonFilt = reasonFilter.value;

    const filtered = allRows.filter(row => {
      // Search filter: check OC ID or delaying member names/IDs
      if (query) {
        const matchesOc = row.ocId.toLowerCase().includes(query);
        const matchesMember = row.members.some(m => 
          m.name.toLowerCase().includes(query) || m.tornId.includes(query)
        );
        if (!matchesOc && !matchesMember) return false;
      }

      // Date range filter
      if (fromVal) {
        const fromTs = new Date(fromVal + 'T00:00:00').getTime() / 1000;
        if (row.execTs < fromTs) return false;
      }
      if (toVal) {
        const toTs = new Date(toVal + 'T23:59:59').getTime() / 1000;
        if (row.execTs > toTs) return false;
      }

      // Reason filter
      if (reasonFilt) {
        const matchesReason = row.members.some(m => m.reasonType === reasonFilt);
        if (!matchesReason) return false;
      }

      return true;
    });

    // Count displaying elements
    if (currentTab === 'leaderboard') {
      // Re-aggregate counts of delay actions per member matching the filters
      const localMemberMap = {};
      filtered.forEach(row => {
        row.members.forEach(m => {
          if (reasonFilt && m.reasonType !== reasonFilt) return;
          if (query && !m.name.toLowerCase().includes(query) && !m.tornId.includes(query)) return;
          
          if (!localMemberMap[m.tornId]) {
            localMemberMap[m.tornId] = { name: m.name, tornId: m.tornId, count: 0, reasonTypes: new Set() };
          }
          localMemberMap[m.tornId].count++;
          localMemberMap[m.tornId].reasonTypes.add(m.reasonType);
        });
      });

      const count = Object.keys(localMemberMap).length;
      resultCount.innerHTML = `Showing <strong>${count}</strong> member${count !== 1 ? 's' : ''}`;
      renderLeaderboard(localMemberMap);
    } else {
      const count = filtered.length;
      resultCount.innerHTML = `Showing <strong>${count}</strong> OC${count !== 1 ? 's' : ''}`;
      renderTable(filtered, query);
    }
  };

  // --- Leaderboard Rendering --- //
  const AVATAR_COLORS = [
    ['#6366f1', '#4f46e5'], ['#f43f5e', '#e11d48'], ['#0ea5e9', '#0284c7'],
    ['#10b981', '#059669'], ['#f59e0b', '#d97706'], ['#a855f7', '#9333ea'],
    ['#ec4899', '#db2777'], ['#14b8a6', '#0d9488']
  ];

  function renderLeaderboard(map) {
    const list = Object.values(map).sort((a, b) => b.count - a.count);
    
    if (list.length === 0) {
      leaderboardList.innerHTML = `
        <div class="empty-state">
          <svg class="empty-icon" xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <h2>No Matching Members</h2>
          <p>Try clearing your search query or filters.</p>
        </div>
      `;
      return;
    }

    const maxCount = list[0].count;

    leaderboardList.innerHTML = list.map((m, i) => {
      const rankClass = i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
      const rankLabel = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i+1}`;
      const colors = AVATAR_COLORS[i % AVATAR_COLORS.length];
      const initials = m.name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();

      const reasonBadges = Array.from(m.reasonTypes).map(r => {
        const labels = { hospital: '🏥 Hospital', traveling: '✈️ Traveling', missing: '⚠️ Missing Item', other: '🔮 Other' };
        return `<span class="badge badge-${r}">${labels[r] || r}</span>`;
      }).join(' ');

      const barPct = Math.round((m.count / maxCount) * 100);
      const profileUrl = `https://www.torn.com/profiles.php?XID=${m.tornId}`;

      return `
        <div class="lb-item fade-in" style="animation-delay: ${Math.min(i * 30, 300)}ms">
          <div class="lb-rank ${rankClass}">${rankLabel}</div>
          <div class="lb-avatar" style="background: linear-gradient(135deg, ${colors[0]}, ${colors[1]})">${initials}</div>
          <div class="lb-info">
            <div class="lb-name"><a href="${profileUrl}" target="_blank" rel="noopener">${escHtml(m.name)}</a></div>
            <div class="lb-id">ID: ${m.tornId}</div>
            <div class="lb-reasons">${reasonBadges}</div>
          </div>
          <div class="lb-count">
            <div class="lb-count-num" style="color: ${colors[0]}">${m.count}</div>
            <div class="lb-count-label">delay${m.count !== 1 ? 's' : ''}</div>
            <div class="lb-bar-wrap"><div class="lb-bar" style="width: ${barPct}%"></div></div>
          </div>
        </div>
      `;
    }).join('');

    // Trigger visual reflow for bar animation
    setTimeout(() => {
      document.querySelectorAll('.lb-bar').forEach(bar => {
        const w = bar.style.width;
        bar.style.width = '0';
        setTimeout(() => { bar.style.width = w; }, 50);
      });
    }, 100);
  }

  // --- OC Table Rendering --- //
  window.sortTable = function(key) {
    if (sortKey === key) {
      sortDir *= -1; // toggle dir
    } else {
      sortKey = key;
      sortDir = -1; // default to descending
    }

    // Toggle header active styles
    document.querySelectorAll('.sortable-header').forEach(th => th.classList.remove('active-sort'));
    const thMap = { id: 'th-id', ready: 'th-ready', exec: 'th-exec', delay: 'th-delay' };
    const thEl = document.getElementById(thMap[sortKey]);
    if (thEl) {
      thEl.classList.add('active-sort');
      const sortIcon = thEl.querySelector('.sort-icon');
      if (sortIcon) sortIcon.textContent = sortDir === -1 ? '↓' : '↑';
    }

    applyFilters();
  };

  function renderTable(rows, query) {
    const keyExtractors = {
      id: r => r.ocId,
      ready: r => r.readyTs,
      exec: r => r.execTs,
      delay: r => r.delaySeconds
    };

    const sorted = [...rows].sort((a, b) => {
      const fn = keyExtractors[sortKey] || keyExtractors.exec;
      const valA = fn(a);
      const valB = fn(b);
      return valA < valB ? sortDir : valA > valB ? -sortDir : 0;
    });

    if (sorted.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="5">
            <div class="empty-state" style="border: none; background: transparent;">
              <svg class="empty-icon" xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <h2>No Matching OCs Found</h2>
              <p>Adjust your search filters.</p>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    tableBody.innerHTML = sorted.map(row => {
      const h = Math.floor(row.delaySeconds / 3600);
      const m = Math.floor((row.delaySeconds % 3600) / 60);
      const delayStr = h > 0 ? `${h}h ${m}m` : `${m}m`;

      const membersHtml = row.members.length === 0
        ? `<span style="color: var(--text-dim); font-size: 12px; font-style: italic;">None (Leader delay / Initiated late)</span>`
        : row.members.map(m => {
            const matchesQuery = query && (m.name.toLowerCase().includes(query) || m.tornId.includes(query));
            const nameStyle = matchesQuery ? 'color: var(--primary); background: rgba(99, 102, 241, 0.1); border-radius: 4px; padding: 0 4px;' : '';
            const profileUrl = `https://www.torn.com/profiles.php?XID=${m.tornId}`;
            const badgeCls = `badge badge-${m.reasonType}`;
            
            const icons = { hospital: '🏥', traveling: '✈️', missing: '⚠️', other: '🔮' };
            const icon = icons[m.reasonType] || '🔮';

            return `
              <div class="member-entry">
                <a href="${profileUrl}" target="_blank" rel="noopener" class="member-name-link" style="${nameStyle}">${escHtml(m.name)} [${m.tornId}]</a>
                <div class="member-reason">
                  <span class="${badgeCls}">${icon} ${m.reasonType}</span>
                  <span>${escHtml(m.reason)}</span>
                </div>
              </div>
            `;
          }).join('');

      return `
        <tr class="fade-in">
          <td class="oc-id">#${escHtml(row.ocId)}</td>
          <td class="time-cell">${escHtml(row.readyUtc)}</td>
          <td class="time-cell">${escHtml(row.execUtc)}</td>
          <td><span class="delay-pill">+${delayStr}</span></td>
          <td><div class="members-cell">${membersHtml}</div></td>
        </tr>
      `;
    }).join('');
  }

  // --- Tab Switching --- //
  window.switchTab = function(tab) {
    currentTab = tab;
    
    // Toggle active state
    document.getElementById('tab-leaderboard').classList.toggle('active', tab === 'leaderboard');
    document.getElementById('tab-ocs').classList.toggle('active', tab === 'ocs');

    if (tab === 'leaderboard') {
      panelLeaderboard.classList.remove('hidden');
      panelOcs.classList.add('hidden');
    } else {
      panelLeaderboard.classList.add('hidden');
      panelOcs.classList.remove('hidden');
    }

    applyFilters();
  };

  // --- Utilities --- //
  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
});

import { useCallback, useEffect, useMemo, useState } from "react";
import { Category, Match, Player, GroupSummary, api } from "../api";

interface Props {
  editable: boolean;
  onChanged: () => void;
}

type GroupFilter = "all" | string;
type ScheduledFilter = "all" | "unscheduled" | "scheduled";

interface MatchWithNames extends Match {
  group_label: string | null;
  category: Category;
  player_a_name: string;
  player_b_name: string;
}

export default function MatchScheduler({ editable, onChanged }: Props) {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [players, setPlayers] = useState<Player[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [matches, setMatches] = useState<MatchWithNames[]>([]);
  const [selectedMatches, setSelectedMatches] = useState<Record<number, boolean>>({});

  // Form State
  const [pastedPhones, setPastedPhones] = useState("");
  const [bulkDate, setBulkDate] = useState("30th");
  const [bulkTime, setBulkTime] = useState("10:30 AM");

  // Filters State
  const [filterGroup, setFilterGroup] = useState<GroupFilter>("all");
  const [filterScheduled, setFilterScheduled] = useState<ScheduledFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Feedback State
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const allGroups = await api.groups();
      setGroups(allGroups);

      const allPlayers = await api.roster();
      setPlayers(allPlayers);

      // Create quick lookup for player names
      const playerMap = new Map<number, string>();
      allPlayers.forEach((p) => {
        playerMap.set(p.id, p.full_name);
      });

      // Load brackets for all categories/groups in parallel
      const brackets = await Promise.all(
        allGroups.map((g) => api.bracket(g.category, g.group_label))
      );

      const allMatches: MatchWithNames[] = [];
      brackets.forEach((b) => {
        b.matches.forEach((m) => {
          // We only schedule matches that are pending or in-progress, and not byes
          if (m.status !== "completed" && !m.is_bye) {
            allMatches.push({
              ...m,
              group_label: b.tournament.group_label,
              category: b.tournament.category,
              player_a_name: m.player_a_id ? playerMap.get(m.player_a_id) || "TBD" : "TBD",
              player_b_name: m.player_b_id ? playerMap.get(m.player_b_id) || "TBD" : "TBD",
            });
          }
        });
      });

      setMatches(allMatches);
    } catch (err: any) {
      setError("Failed to load tournament data. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Normalize phone numbers (retain digits, match last 10 digits to be safe)
  const normalize = (phone: string) => {
    const cleaned = phone.replace(/\D/g, "");
    return cleaned.slice(-10);
  };

  // Helper: Schedule matches by pasting phone numbers
  async function handleScheduleByPhones() {
    if (!pastedPhones.trim()) {
      setError("Please paste one or more phone numbers.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);

    const targetPhones = pastedPhones
      .split(/[\n,;]+/)
      .map((x) => normalize(x))
      .filter(Boolean);

    if (targetPhones.length === 0) {
      setError("No valid phone numbers found in the pasted text.");
      setBusy(false);
      return;
    }

    const matchedPlayerIds = new Set<number>();
    const matchedPhones = new Set<string>();
    const unknownPhones: string[] = [];

    players.forEach((p) => {
      if (p.phone) {
        const normP = normalize(p.phone);
        if (targetPhones.includes(normP)) {
          matchedPlayerIds.add(p.id);
          matchedPhones.add(normP);
        }
      }
    });

    targetPhones.forEach((phone) => {
      if (!matchedPhones.has(phone)) {
        unknownPhones.push(phone);
      }
    });

    if (matchedPlayerIds.size === 0) {
      setError("No registered players match the provided phone numbers.");
      setBusy(false);
      return;
    }

    // Find active/pending matches involving these players
    const matchesToSchedule = matches.filter(
      (m) =>
        (m.player_a_id && matchedPlayerIds.has(m.player_a_id)) ||
        (m.player_b_id && matchedPlayerIds.has(m.player_b_id))
    );

    if (matchesToSchedule.length === 0) {
      setError("No active or pending matches found for these players.");
      setBusy(false);
      return;
    }

    const scheduledTimeStr = `${bulkDate} ${bulkTime}`.trim();

    try {
      await Promise.all(
        matchesToSchedule.map((m) => api.setSchedule(m.id, scheduledTimeStr))
      );

      let successMsg = `Successfully scheduled ${matchesToSchedule.length} match(es) on the ${scheduledTimeStr}.`;
      if (unknownPhones.length > 0) {
        successMsg += ` (Note: ${unknownPhones.length} phone(s) did not match any player).`;
      }
      setMessage(successMsg);
      setPastedPhones("");
      loadData();
      onChanged();
    } catch (err: any) {
      setError("An error occurred while setting match times.");
    } finally {
      setBusy(false);
    }
  }

  // Helper: Schedule selected checkbox matches
  async function handleScheduleSelected() {
    const selectedIds = Object.keys(selectedMatches)
      .map(Number)
      .filter((id) => selectedMatches[id]);

    if (selectedIds.length === 0) {
      setError("Please select at least one match from the list below.");
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);

    const scheduledTimeStr = `${bulkDate} ${bulkTime}`.trim();

    try {
      await Promise.all(
        selectedIds.map((id) => api.setSchedule(id, scheduledTimeStr))
      );

      setMessage(`Successfully scheduled ${selectedIds.length} selected match(es) on the ${scheduledTimeStr}.`);
      setSelectedMatches({});
      loadData();
      onChanged();
    } catch (err: any) {
      setError("An error occurred while scheduling selected matches.");
    } finally {
      setBusy(false);
    }
  }

  // Filter matches based on sidebar/controls selection
  const filteredMatches = useMemo(() => {
    return matches.filter((m) => {
      // 1. Group filter
      if (filterGroup !== "all") {
        const [cat, grp] = filterGroup.split(":");
        if (m.category !== cat) return false;
        if (grp === "null") {
          if (m.group_label !== null) return false;
        } else {
          if (m.group_label !== grp) return false;
        }
      }

      // 2. Scheduled/Unscheduled filter
      if (filterScheduled === "unscheduled" && m.scheduled_time) return false;
      if (filterScheduled === "scheduled" && !m.scheduled_time) return false;

      // 3. Search query (players name)
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const aName = m.player_a_name.toLowerCase();
        const bName = m.player_b_name.toLowerCase();
        if (!aName.includes(query) && !bName.includes(query)) return false;
      }

      return true;
    });
  }, [matches, filterGroup, filterScheduled, searchQuery]);

  const allSelected = filteredMatches.length > 0 && filteredMatches.every((m) => selectedMatches[m.id]);

  const toggleSelectAll = () => {
    if (allSelected) {
      const next = { ...selectedMatches };
      filteredMatches.forEach((m) => {
        delete next[m.id];
      });
      setSelectedMatches(next);
    } else {
      const next = { ...selectedMatches };
      filteredMatches.forEach((m) => {
        next[m.id] = true;
      });
      setSelectedMatches(next);
    }
  };

  const toggleSelectMatch = (id: number) => {
    setSelectedMatches((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  if (loading) return <div className="py-10 text-center text-slate-400">Loading…</div>;

  return (
    <div className="space-y-6 text-sm">
      {/* Messages */}
      {message && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-lg">
          {message}
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Inputs for Date and Time */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4">
        <h3 className="font-semibold text-slate-700">1. Select Target Schedule Time</h3>
        <div className="flex flex-wrap gap-4 items-end">
          <label className="flex flex-col gap-1 text-xs text-slate-500 font-medium">
            Date
            <select
              value={bulkDate}
              onChange={(e) => setBulkDate(e.target.value)}
              className="w-32 rounded border border-slate-200 px-2 py-1.5 bg-white text-slate-700"
            >
              <option value="29th">29th</option>
              <option value="30th">30th</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500 font-medium">
            Time / Details (e.g. 10:30 AM, or Sat 5:00 PM Court 1)
            <input
              type="text"
              value={bulkTime}
              onChange={(e) => setBulkTime(e.target.value)}
              placeholder="e.g. 10:30 AM"
              className="w-72 rounded border border-slate-200 px-2 py-1.5 bg-white text-slate-700"
            />
          </label>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        {/* Option A: Paste Phone Numbers */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-3 flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-slate-700 mb-1">Option A: Schedule by Phone Numbers</h3>
            <p className="text-xs text-slate-400 mb-2">
              Paste phone numbers (one per line, comma or semicolon separated). The system will search for their upcoming matches and schedule them.
            </p>
            <textarea
              value={pastedPhones}
              onChange={(e) => setPastedPhones(e.target.value)}
              rows={6}
              placeholder="+91 98765 43210&#10;+91 99999 88888"
              className="w-full rounded border border-slate-200 p-2 font-mono text-xs text-slate-700"
            />
          </div>
          <button
            onClick={handleScheduleByPhones}
            disabled={busy || !editable}
            className="w-full bg-court text-white px-4 py-2 rounded-lg font-medium disabled:opacity-40"
          >
            {busy ? "Scheduling…" : "Schedule Matches"}
          </button>
        </div>

        {/* Option B Info */}
        <div className="md:col-span-2 bg-white border border-slate-200 rounded-xl p-4 space-y-4 flex flex-col">
          <div className="flex justify-between items-center flex-wrap gap-2">
            <h3 className="font-semibold text-slate-700">Option B: Select Matches to Schedule</h3>
            <button
              onClick={handleScheduleSelected}
              disabled={busy || !editable}
              className="bg-court text-white px-4 py-1.5 rounded-lg font-medium text-xs disabled:opacity-40"
            >
              Schedule Checked ({Object.values(selectedMatches).filter(Boolean).length})
            </button>
          </div>

          {/* Filters */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
            <select
              value={filterGroup}
              onChange={(e) => setFilterGroup(e.target.value)}
              className="rounded border border-slate-200 p-1.5 text-slate-700 bg-white"
            >
              <option value="all">All Groups</option>
              {groups
                .sort((a, b) => {
                  if (a.category !== b.category) return a.category.localeCompare(b.category);
                  return (a.group_label ?? "").localeCompare(b.group_label ?? "");
                })
                .map((g) => (
                  <option key={`${g.category}:${g.group_label}`} value={`${g.category}:${g.group_label}`}>
                    {g.category === "men" ? `Men Group ${g.group_label}` : "Women Main"}
                  </option>
                ))}
            </select>

            <select
              value={filterScheduled}
              onChange={(e) => setFilterScheduled(e.target.value as ScheduledFilter)}
              className="rounded border border-slate-200 p-1.5 text-slate-700 bg-white"
            >
              <option value="all">All Scheduling Status</option>
              <option value="unscheduled">Unscheduled Only</option>
              <option value="scheduled">Scheduled Only</option>
            </select>

            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search player name…"
              className="rounded border border-slate-200 p-1.5 text-slate-700"
            />
          </div>

          {/* Matches List */}
          <div className="flex-1 overflow-y-auto max-h-80 border border-slate-200 rounded-lg">
            {filteredMatches.length === 0 ? (
              <div className="py-8 text-center text-slate-400 text-xs">
                No matching upcoming matches found.
              </div>
            ) : (
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-slate-50 text-slate-500 sticky top-0 uppercase text-[10px] border-b border-slate-200">
                  <tr>
                    <th className="px-3 py-2 w-8">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th className="px-3 py-2">Match details</th>
                    <th className="px-3 py-2">Group</th>
                    <th className="px-3 py-2">Scheduled time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {filteredMatches.map((m) => (
                    <tr key={m.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={!!selectedMatches[m.id]}
                          onChange={() => toggleSelectMatch(m.id)}
                        />
                      </td>
                      <td className="px-3 py-2.5 font-medium">
                        {m.player_a_name} <span className="text-slate-400 font-normal">vs</span> {m.player_b_name}
                        <div className="text-[10px] text-slate-400 font-normal mt-0.5">
                          Round {m.round_number} (Match {m.position_in_round + 1})
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-slate-500">
                        {m.category === "men" ? `Men ${m.group_label}` : "Women"}
                      </td>
                      <td className="px-3 py-2.5">
                        {m.scheduled_time ? (
                          <span className="bg-indigo-50 border border-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded text-[10px]">
                            {m.scheduled_time}
                          </span>
                        ) : (
                          <span className="text-slate-400 italic">Unscheduled</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Presentation view v2: the contract between story.ts (state), stage.ts (shell) and the renderers
// band.ts, relief.ts and weeks.ts. See docs/architecture-presentation-v2.md.
import type { Body, PairExplanation, Preset, Twin, TwinsResponse } from '../api';

export type Step = 1 | 2 | 3 | 4 | 5 | 6 | 7;
export const STEP_NAMES: Record<Step, string> = {
  1: 'Target', 2: 'Search', 3: 'Result', 4: 'Why', 5: 'When', 6: 'Bulgaria', 7: 'Limits',
};

/** One week of /api/calendar for one row. */
export interface Week { week: number; start: string; light_sim: number }
export interface CalendarRow {
  kind: string; label: string; lat: number; lon: number; weeks: Week[];
  best_window?: { start: string; end: string; light_sim: number; distinct?: boolean | null } | null;
}
export interface CalendarResponse { target: { body: Body; lat: number; lon: number }; rows: CalendarRow[]; caption: string; source: string }

/** A fetched value: undefined = not asked yet, 'loading', an Error, or the value. */
export type Slot<T> = undefined | 'loading' | Error | T;

export interface StoryState {
  presets: Preset[];
  presetId: string | null;
  target: Preset | null;            // the selected preset (body, lat, lon, label)
  res: Slot<TwinsResponse>;         // twins for the target
  twins: Twin[];                    // ranked list shown on the stage (all destination bodies, Earth first)
  twinIdx: number;                  // index into twins of the selected twin
  pair: Slot<PairExplanation>;      // /api/pair for target ↔ selected twin
  calendar: Slot<CalendarResponse>; // /api/calendar for the selected twin (Earth twins of Moon/Mars targets only)
  bulgaria: Slot<Twin | null>;      // best Bulgarian cell, vegetation filter off; null = none found
  step: Step;
  steps: Step[];                    // steps available for this target (Earth targets skip 5 and 6)
}

/** Every renderer is a pure function of the state into its own root element; it may attach listeners. */
export type Render = (root: HTMLElement, s: StoryState, act: Actions) => void;

export interface Actions {
  go(step: Step): void;
  next(): void;
  prev(): void;
  preset(id: string): void;
  twin(i: number): void;
  retry(): void;
}

export const selectedTwin = (s: StoryState): Twin | null => s.twins[s.twinIdx] ?? null;

// src/store/selectors.ts
import { shallow } from "zustand/shallow";
import { useProjectStore } from "./projectStore";

// Factory selector so its identity is stable via useMemo in components
export const makeProjectsSelector = (roleId?: number) => (
  s: ReturnType<typeof useProjectStore.getState>
) => (roleId ? s.projectsByRole[roleId] : undefined) ?? [];

export const baseProjectSlice = (
  s: ReturnType<typeof useProjectStore.getState>
) => ({
  projectId: s.projectId,
  isLoading: s.isLoading,
});
export const baseProjectSliceShallow = shallow;

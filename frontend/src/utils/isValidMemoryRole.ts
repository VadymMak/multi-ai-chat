// File: src/utils/isValidMemoryRole.ts

import { MemoryRole } from "../types/memory";

// Use `unknown` to allow type predicate `role is MemoryRole` safely
export const isValidMemoryRole = (role: unknown): role is MemoryRole => {
  return (
    typeof role === "string" &&
    [
      "LLM Engineer",
      "Vessel Engineer",
      "ML Engineer",
      "Data Scientist",
      "Frontend Developer",
      "Python Developer",
      "Esoteric Knowledge",
    ].includes(role)
  );
};

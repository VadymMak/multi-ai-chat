// File: src/utils/isValidMemoryRole.ts

import { MemoryRole } from "../types/memory";

export const isValidMemoryRole = (role: string): role is MemoryRole => {
  return [
    "LLM Engineer",
    "Vessel Engineer",
    "ML Engineer",
    "Data Scientist",
    "Frontend Developer",
    "Python Developer",
    "Esoteric Knowledge",
  ].includes(role);
};

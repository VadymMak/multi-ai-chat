export interface MemoryRole {
  id: number;
  name: string;
}

export const knownRoles: MemoryRole[] = [
  { id: 1, name: "LLM Engineer" },
  { id: 2, name: "Vessel Engineer" },
  { id: 3, name: "ML Engineer" },
  { id: 4, name: "Data Scientist" },
  { id: 5, name: "Frontend Developer" },
  { id: 6, name: "Python Developer" },
  { id: 7, name: "Esoteric Knowledge" },
];

export const getKnownRoles = () => knownRoles;

import React from "react";

interface RoleOption {
  id: number;
  name: string;
}

interface Props {
  selectedRole: number;
  onChange: (roleId: number) => void;
}

// ✅ You can update or load this list from the backend later
const roles: RoleOption[] = [
  { id: 1, name: "Frontend Engineer" },
  { id: 2, name: "LLM Engineer" },
  { id: 3, name: "Data Scientist" },
  { id: 4, name: "Esoteric Researcher" },
];

const RoleSelector: React.FC<Props> = ({ selectedRole, onChange }) => {
  return (
    <div className="flex flex-col gap-1">
      <label
        htmlFor="role-select"
        className="text-sm font-medium text-gray-700"
      >
        Select Role
      </label>
      <select
        id="role-select"
        className="p-2 rounded border border-gray-300 bg-white text-sm"
        value={selectedRole}
        onChange={(e) => onChange(Number(e.target.value))} // 👈 ensure integer
      >
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </select>
    </div>
  );
};

export default RoleSelector;

// src/components/Settings/ProjectContextMenu.tsx
import React, { useRef, useEffect } from "react";
import { Settings, Edit, Trash2, Copy } from "lucide-react";

interface ProjectContextMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenSettings: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  anchorEl: HTMLElement | null;
}

const ProjectContextMenu: React.FC<ProjectContextMenuProps> = ({
  isOpen,
  onClose,
  onOpenSettings,
  onRename,
  onDuplicate,
  onDelete,
  anchorEl,
}) => {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(event.target as Node) &&
        anchorEl &&
        !anchorEl.contains(event.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onClose, anchorEl]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen || !anchorEl) return null;

  // Calculate position
  const rect = anchorEl.getBoundingClientRect();
  const menuStyle: React.CSSProperties = {
    position: "fixed",
    top: rect.bottom + 4,
    right: window.innerWidth - rect.right,
    zIndex: 1000,
  };

  return (
    <div
      ref={menuRef}
      style={menuStyle}
      className="min-w-[200px] bg-panel border border-border rounded-lg shadow-xl overflow-hidden animate-in fade-in slide-in-from-top-2 duration-200"
    >
      <div className="py-1">
        <MenuItem
          icon={<Settings size={16} />}
          label="Project Settings"
          onClick={() => {
            onOpenSettings();
            onClose();
          }}
        />
        <MenuItem
          icon={<Edit size={16} />}
          label="Rename"
          onClick={() => {
            onRename();
            onClose();
          }}
        />
        <MenuItem
          icon={<Copy size={16} />}
          label="Duplicate"
          onClick={() => {
            onDuplicate();
            onClose();
          }}
        />
        <div className="h-px bg-border my-1" />
        <MenuItem
          icon={<Trash2 size={16} />}
          label="Delete"
          onClick={() => {
            onDelete();
            onClose();
          }}
          variant="danger"
        />
      </div>
    </div>
  );
};

// Menu Item Component
const MenuItem: React.FC<{
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  variant?: "default" | "danger";
}> = ({ icon, label, onClick, variant = "default" }) => {
  const isDanger = variant === "danger";

  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
        isDanger
          ? "text-error hover:bg-error/10"
          : "text-text-primary hover:bg-surface"
      }`}
    >
      <span className={isDanger ? "text-error" : "text-text-secondary"}>
        {icon}
      </span>
      <span className="font-medium">{label}</span>
    </button>
  );
};

export default ProjectContextMenu;

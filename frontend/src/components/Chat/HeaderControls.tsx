import AiSelector from "../../features/aiConversation/AiSelector";
import MemoryRoleSelector from "../../features/aiConversation/MemoryRoleSelector";
import ProjectSelector from "../../features/aiConversation/ProjectSelector";

interface HeaderControlsProps {
  showPromptPicker: boolean;
  setShowPromptPicker: (val: boolean) => void;
}

const HeaderControls: React.FC<HeaderControlsProps> = ({
  showPromptPicker,
  setShowPromptPicker,
}) => {
  const handleToggle = () => {
    setShowPromptPicker(!showPromptPicker);
  };

  return (
    <div className="sticky top-0 z-10 bg-white border-b p-3 shadow-sm">
      <div className="flex flex-wrap gap-2 justify-center sm:justify-start mb-2">
        <AiSelector />
        <button
          onClick={handleToggle}
          className="px-3 py-1.5 text-sm bg-orange-100 border border-orange-400 text-orange-800 rounded-lg hover:bg-orange-200"
        >
          ✨ Prompt Library
        </button>
      </div>
      <div className="flex flex-wrap gap-2 justify-center sm:justify-start">
        <MemoryRoleSelector />
        <ProjectSelector />
      </div>
    </div>
  );
};

export default HeaderControls;

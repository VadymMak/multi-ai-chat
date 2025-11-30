// File: frontend/src/utils/projectStructureParser.ts
/**
 * Parser for Project Builder output structures
 */

export interface ParsedFile {
  number: number;
  path: string;
  description: string;
  status: "ready" | "generating" | "done" | "error";
  code?: string;
}

export interface ParsedProjectStructure {
  projectName: string;
  tech: string;
  files: ParsedFile[];
  setupCommands: string[];
}

/**
 * Check if text contains Project Builder markers
 */
export function isProjectStructure(text: string): boolean {
  const markers = [
    "===PROJECT_STRUCTURE_START===",
    "===FINAL_STRUCTURE_START===",
    "===PROJECT_STRUCTURE_END===",
    "===FINAL_STRUCTURE_END===",
  ];
  return markers.some((marker) => text.includes(marker));
}

/**
 * Parse project structure from AI output
 */
export function parseProjectStructure(
  text: string
): ParsedProjectStructure | null {
  if (!isProjectStructure(text)) {
    return null;
  }

  const result: ParsedProjectStructure = {
    projectName: "",
    tech: "",
    files: [],
    setupCommands: [],
  };

  // Extract project name: 📁 PROJECT_NAME or # 📁 PROJECT_NAME
  const projectNameMatch = text.match(/[#\s]*📁\s*\[?([^\]\n\r✅]+)/);
  if (projectNameMatch) {
    result.projectName = projectNameMatch[1].trim();
  }

  // Extract tech stack: Tech: xxx or **Tech:** xxx
  const techMatch = text.match(/\*?\*?Tech:?\*?\*?\s*([^\n\r]+)/i);
  if (techMatch) {
    result.tech = techMatch[1].trim();
  }

  // Extract files with pattern: filename [number] - description
  // Supports: ├── file.ts [1] - description
  //           │   ├── nested.ts [2] - description
  //           └── last.ts [3] - description
  const fileRegex = /[├└─│\s]*([^\s\[]+)\s*\[(\d+)\]\s*[-–—]\s*([^\n\r]+)/g;
  let match;
  while ((match = fileRegex.exec(text)) !== null) {
    const [, path, numStr, description] = match;
    const num = parseInt(numStr, 10);
    if (!isNaN(num) && path) {
      result.files.push({
        number: num,
        path: path.trim(),
        description: description.trim(),
        status: "ready",
      });
    }
  }

  // Sort files by number
  result.files.sort((a, b) => a.number - b.number);

  // Extract setup commands from ```bash blocks
  const bashBlockRegex = /```bash\n([\s\S]*?)```/g;
  let bashMatch;
  while ((bashMatch = bashBlockRegex.exec(text)) !== null) {
    const commands = bashMatch[1]
      .split("\n")
      .map((cmd: string) => cmd.trim())
      .filter((cmd: string) => cmd && !cmd.startsWith("#"));
    result.setupCommands.push(...commands);
  }

  // Also check for 📋 SETUP COMMANDS: section (non-code-block)
  const setupSection = text.match(
    /📋\s*SETUP COMMANDS:?\s*\n([\s\S]*?)(?=\n(?:📦|🔗|##|===)|$)/i
  );
  if (setupSection) {
    const lines = setupSection[1]
      .split("\n")
      .map((l: string) => l.replace(/^[\d\.\-\*\s]+/, "").trim())
      .filter((l: string) => l && !l.startsWith("#") && l.length > 3);
    result.setupCommands.push(...lines);
  }

  return result;
}

/**
 * Extract just the structure section from full text
 */
export function extractStructureSection(text: string): string {
  // Try FINAL first
  const finalMatch = text.match(
    /===FINAL_STRUCTURE_START===\s*([\s\S]*?)\s*===FINAL_STRUCTURE_END===/
  );
  if (finalMatch) return finalMatch[1].trim();

  // Then PROJECT
  const projectMatch = text.match(
    /===PROJECT_STRUCTURE_START===\s*([\s\S]*?)\s*===PROJECT_STRUCTURE_END===/
  );
  if (projectMatch) return projectMatch[1].trim();

  return text;
}

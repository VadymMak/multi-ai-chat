// Utility to log session flow changes with timestamp
export const logSessionFlow = (label: string, data: Record<string, any>) => {
  const time = new Date().toISOString().split("T")[1].replace("Z", "");
  console.log(
    `%c[SessionFlow][${time}] ${label}`,
    "color: #4CAF50; font-weight: bold;",
    data
  );
};

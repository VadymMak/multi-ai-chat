// jest.config.js
module.exports = {
  preset: "ts-jest",
  testEnvironment: "jsdom",
  transform: {
    "^.+\\.(ts|tsx)$": "babel-jest",
  },
  moduleFileExtensions: ["ts", "tsx", "js", "jsx"],
  transformIgnorePatterns: [
    "/node_modules/(?!axios)/", // 👈 let Jest transform Axios which is ESM
  ],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
};

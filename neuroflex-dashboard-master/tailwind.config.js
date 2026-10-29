/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./accounts/**/*.py",
    "./audit/**/*.py",
    "./dashboard/**/*.py",
    "./reports/**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f4f7fb",
          100: "#e6edf5",
          300: "#aac0d4",
          500: "#4c6f8f",
          700: "#1f4e6b",
          800: "#183b52",
          900: "#102938",
        },
        mist: "#f7f9fc",
        border: "#d7e0ea",
        success: "#1f7a52",
        warning: "#b7791f",
        danger: "#b42318",
      },
      boxShadow: {
        panel: "0 8px 24px rgba(16, 41, 56, 0.08)",
      },
      borderRadius: {
        panel: "1rem",
      },
      fontFamily: {
        sans: ["Segoe UI", "Tahoma", "Geneva", "Verdana", "sans-serif"],
      },
    },
  },
  plugins: [],
};

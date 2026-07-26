/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        court: "#0f766e", // teal accent, evokes a badminton court
      },
    },
  },
  plugins: [],
};

import tseslint from 'typescript-eslint';

// src/ holds the generated modules plus copies of the committed helpers.ts
// and lookup.ts (tools/package/build.py), so linting src/ covers both.
// test/generated/ (megabytes of data literals) is only type-checked by tsc.
export default tseslint.config(
  {
    files: ['src/**/*.ts', 'test/*.ts'],
    extends: [tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        project: './tsconfig.eslint.json',
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // `const { _source, ...rest } = r` is how a field is dropped from a record.
      '@typescript-eslint/no-unused-vars': ['error', { ignoreRestSiblings: true }],
    },
  },
  {
    // The schema spells some fields `Entity.<Enum> | number` (a raw DCS value
    // outside the enum is kept); the enum part documents the known values.
    files: ['src/types.ts'],
    rules: { '@typescript-eslint/no-redundant-type-constituents': 'off' },
  },
);

# Invalid Pak Examples

These files demonstrate **illegal** Pak code. Each file is intentionally broken.
The comments explain what is wrong and what the correct form is.

They exist to help AI models learn the edges of the language,
not just the happy path.

| File | What it demonstrates |
|------|---------------------|
| `no_main.pak` | `fn main()` instead of `entry {}` |
| `wrong_operators.pak` | C-style `&&`, `||`, `!` |
| `implicit_cast.pak` | Implicit numeric conversion |
| `wrong_result.pak` | Wrong Result syntax |
| `int_match.pak` | Matching on integer values |
| `exceptions.pak` | Exception-style error handling |
| `semicolons.pak` | Rust/C-style semicolons on every line |
| `null_keyword.pak` | Using `null` instead of `none` |
| `void_return.pak` | Declaring `-> void` return type |
| `wrong_containers.pak` | Invented container APIs |

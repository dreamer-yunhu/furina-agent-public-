# 结构体（struct）、方法与 Trait

> 由 `泛型，生命周期，Trait.txt` 美化整理。
> **注意**：本篇文件名标的是《泛型，生命周期，Trait》，实际笔记主体是 **struct 结构体 + impl 方法 + 关联函数 + Debug Trait**。
> 真正的泛型 / 生命周期 / Trait 在正文里已经冒出两个"伏笔"，文末给出了衔接指引。

---

## 一、结构体 struct（类比 Python 的 class）

### 1.1 定义与实例化

```rust
struct User {              // 关键字 struct + 名称
    name: String,
    age: u8,
    email: String,
    hobby: String,
}
```

- 定义：`struct 名称 { 字段: 类型, ... }`。
- 实例化：以**键值对**形式创建。
- 读取字段：用 `.字段名`。

```rust
fn build_user(name: String, age: u8, email: String, hobby: String) -> User {
    User {
        name,     // 字段初始化简写：形参与字段同名时，可省略 "字段名:" 前缀
        age,      // 直接写形参名即可
        email,
        hobby,
    }
}
```

### 1.2 可变性

```rust
let mut user1 = User {
    name: String::from("Van"),
    age: 60,
    email: String::from("114514@outlook.com"),
    hobby: String::from("BDSM"),
};

user1.age = 18;          // ✅ 实例本身是 mut 的，字段才能被赋值修改
println!("{}", user1.age);
```

> 结构体实例**本身不可变**时，字段也不可变；想改字段，实例变量必须声明为 `mut`。

### 1.3 更新语法

```rust
let user2 = User {
    name: String::from("田所浩二"),
    age: 24,
    ..user1               // 剩下的字段从 user1 补齐
};
```

> 注意：`..user1` 会把 user1 中**未实现 Copy 的字段所有权移动**到 user2（这里移动了 email / hobby）。若之后还想用 user1，会报错。

### 1.4 变体结构体（顺便一提）

```rust
struct Number(i32, i32, i32);   // 元组结构体：定义特定结构的元组用
struct Empty;                    // 单元结构体：不含任何字段
```

### 1.5 一个伏笔

> **结构体里的数据来源可以是引用**（存 `&str` 等），但**必须显式写生命周期参数**，否则编译器不知道引用能活多久。
> —— 这正是"生命周期"主题的开端，文末有衔接。

---

## 二、打印结构体：手动实现 Debug Trait

```rust
#[derive(Debug)]          // 结构体没有内置 Debug Trait，必须这样注解后才能 {:?} 打印
struct Rectangle {
    width: u32,
    length: u32,
}
```

```rust
println!("{:?}", rect);   // 单行紧凑输出
println!("{:#?}", rect);  // # 号开启"美化输出"：复杂结构会带缩进，更易读
```

> 这里的 `#[derive(Debug)]` 本身就是 **Trait（特征）**的自动派生语法。

---

## 三、方法：用 impl 定义

- 结构体本身只存数据，**方法**写在 `impl 结构体名 { ... }` 块里。
- 调用方式：`对象.方法()`——Rust 会自动补上方法的签名（自动引用 / 解引用 `&self`）。

```rust
#[derive(Debug)]
struct Rectangle {
    width: u32,
    length: u32,
}

impl Rectangle {
    // 方法：第一个参数 &self 代表"当前实例"
    fn area(&self) -> u32 {
        self.width * self.length
    }

    fn can_hold(&self, other: &Rectangle) -> bool {
        self.width > other.width && self.length > other.length
    }

    // 关联函数：位于结构体命名空间、但"没有 self 参数"的函数
    // 通常用作构造函数（Rust 惯例叫 new）
    fn square(size: u32) -> Rectangle {
        Rectangle {
            width: size,
            length: size,
        }
    }
}

fn main() {
    let rectangle1 = Rectangle { width: 10, length: 20 };
    let rectangle2 = Rectangle { width: 20, length: 40 };

    println!("Rect is {:#?}", Rectangle::square(20));   // :: 调用关联函数
    println!("{}", rectangle1.can_hold(&rectangle2));   // false
    println!("The area of the rectangle is {}", rectangle1.area()); // 200
}
```

关键点小结：

| 概念 | 语法 | 说明 |
|---|---|---|
| **方法** | `fn area(&self)` | 第一个参数是 `self`，随实例调用 |
| **关联函数** | `fn square(size: u32)` | 没有 `self`，用 `类型::函数名` 调用，常当构造函数 |
| **多个 impl** | `impl A{} impl A{}` | 一个结构体可以有多个 impl 块 |

---

## 四、衔接：本系列真正的"泛型 / 生命周期 / Trait"

标题里的三个主题，本篇笔记已经埋了引线，后续对照展开：

1. **Trait**：`#[derive(Debug)]` 是 Trait 的自动实现；`to_string()` 需要类型实现 `Display`（HashMap 篇里见过）。Trait = 一组方法签名的集合，定义"能做什么"。
2. **生命周期（lifetime）**：结构体字段想存引用，就必须写生命周期参数（见 1.5）——Rust 用它保证引用不会悬空。
3. **泛型（generic）**：`Vec<T>`、`Option<T>` 里的 `T` 就是泛型占位——让一份代码适配多种类型（见《常见数据集合》篇的 `Vec<T>`）。

> 学习顺序建议：先 `enum + match`（见《枚举》篇），再回来啃 泛型 → Trait → 生命周期，三者往往要一起用才能真正写"零开销抽象"的代码。

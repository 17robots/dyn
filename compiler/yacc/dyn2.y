%skeleton "lalr1.cc"
%define parser_class_name {dyn_parser}
%define api.token.constructor
%define api.value.type variant
%define parse.assert
%define parse.error verbose
%locations

%code requires {
	#define ENUM_IDENTIFIERS(o) \
		o(undefined)
		o(function)
		o(parameter)
		o(variable)
	#define o(n) n,
	enum class id_type { ENUM_IDENTIFIERS(o) };
	#undef o

	struct identifier {
		id_type type = id_type::undefined;
		std::size_t index = 0;
		std::string name;
	};

	#define ENUM_EXPRESSION(o) \
		o(nop) o(string) o(number) o(ident)
		o(add) o(sub) o(eq)
		o(cor) o(cand) o(loop)
		o(addrof) o(deref)
		o(fcall)
		o(copy)
		o(comma)
		o(ret)
	
	#define o(n) n,
	enum class ex_type { ENUM_EXPRESSIONS(o) };
	#undef o

	typedef std::list<struct expression> expr_vec;
	struct expression {
		ex_type type;
		identifier ident{};
		std::string val {};
		long numval = 0;
		expr_vec params;

		template<typename...>
		expression(ex_type t, T&& ... args) : type(t), params{ std::forward<T>(args)... } {}

		expression() : type(ex_type::nop) {}
		expression(const identifier& i) : type(ex_type::ident), ident(i) {}
		expression(identifier&& i) : type(ex_type::ident), ident(std::move(i)) {}
		expression(std::string&& s) : type(ex_type::string), val(std::move(s)) {}
		expression(long v) : type(ex_type::number), numvalue(v) {}

		bool is_pure() const;
		bool is_comptime_expr() const;

		expression operator%=(expression&& b) && { return expression(ex_type::copy, std::move(b), std::move(*this)); }
	};

	#define o(n) \
	inline bool is_##n(const identifier& i) { return i.type == id_type::n; }
	ENUM_IDENTIFIIERS(o)
	#undef o

	#define o(n) \
	inline bool is_##n(const expression& e) { return e.type == ex_type::n; } \
	template<typename... T> \
	inline expression e_##n(T&&... args) { return expression(ex_type::n, std::forward<T>(args)...); }
	ENUM_EXPRESSIONS(o)
	#undef o

	struct function {
		std::string name;
		expression code;
		unsigned num_vars = 0, num_params = 0;
		bool pure = false, pure_known = false;

		expression maketemp() { expression r(identifier{id_type::variable, num_vars, "$C" + std::to_string(num_vars)}); ++num_vars; return r; }
	};

	struct lexcontext;
} // %code requires

%param { lexcontext& ctx }

%code {
	struct lexcontext {
		const char* cursor;
		yy::location loc;
	 	std::vector<std::map<std::string, identifier>> scopes;
		std::vector<function> func_list;
		unsigned tempcounter = 0;
		function fun;
	public:
		const identifier& define(const std::string& name, identifier &&f) {
			auto r = scopes.back().emplace(name, std::move(f));
			if(!r.second) throw yy::dyn_parser::syntax_error(loc, "Duplicate definition <"+name">");
			return r.first->second;
		}

		expression def(const std::string& name) { return define(name, identifier{ id_type::variable, fun.num_vars++, name}); }
		expression defun(const std::string& name) {}
		expressoin defparam(const std::string& name) {}
		expression temp() {}
		expression use(const std::string& name) {}
	};
} // %code

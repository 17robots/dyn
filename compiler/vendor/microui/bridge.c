#include <microui.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
typedef struct { mu_Context ui; mu_Command *cursor; bool active, window, exhausted, ready; } DynUi;
static int text_width(mu_Font font,const char *text,int length) { (void)font;return 8*(length<0?(int)strlen(text):length); }
static int text_height(mu_Font font) { (void)font;return 16; }
size_t dyn_mu_size(void) { return sizeof(DynUi); }
size_t dyn_mu_align(void) { return _Alignof(DynUi); }
void dyn_mu_init(DynUi *s) { memset(s,0,sizeof(*s));mu_init(&s->ui);s->ui.text_width=text_width;s->ui.text_height=text_height; }
bool dyn_mu_begin(DynUi *s) { if (!s || s->active) return false;mu_begin(&s->ui);s->active=true;s->ready=false;s->cursor=NULL;s->exhausted=false;return true; }
bool dyn_mu_end(DynUi *s) { if (!s || !s->active || s->window) return false;mu_end(&s->ui);s->active=false;s->ready=true;return true; }
static bool room(DynUi *s,const char *text) {
    return text && strlen(text)<=4096 && s->ui.command_list.idx < MU_COMMANDLIST_SIZE-8192;
}
bool dyn_mu_window(DynUi *s,const char *title,int x,int y,int w,int h) {
    if (!s || !s->active || s->window || !room(s,title) || w<=0 || h<=0 || w>1000000 || h>1000000 || x<-1000000 || x>1000000 || y<-1000000 || y>1000000 || s->ui.root_list.idx>=MU_ROOTLIST_SIZE-1) return false;
    s->window=mu_begin_window(&s->ui,title,mu_rect(x,y,w,h))!=0;return s->window;
}
bool dyn_mu_window_end(DynUi *s) { if (!s || !s->window) return false;mu_end_window(&s->ui);s->window=false;return true; }
bool dyn_mu_label(DynUi *s,const char *text) {
    if (!s || !s->window || !room(s,text)) return false;
    int width=-1;mu_layout_row(&s->ui,1,&width,0);mu_label(&s->ui,text);return true;
}
int dyn_mu_button(DynUi *s,const char *text) {
    if (!s || !s->window || !room(s,text)) return -1;
    int width=-1;mu_layout_row(&s->ui,1,&width,0);return mu_button(&s->ui,text)!=0;
}
void dyn_mu_mouse(DynUi *s,int x,int y,int action) {
    if (!s || s->active || x<-1000000 || x>1000000 || y<-1000000 || y>1000000) return;
    mu_input_mousemove(&s->ui,x,y);
    if (action==1) mu_input_mousedown(&s->ui,x,y,MU_MOUSE_LEFT);
    if (action==2) mu_input_mouseup(&s->ui,x,y,MU_MOUSE_LEFT);
}
mu_Command *dyn_mu_next(DynUi *s) {
    if (!s || s->active || s->exhausted) return NULL;
    if (!mu_next_command(&s->ui,&s->cursor)) { s->exhausted=true;return NULL; }
    return s->cursor;
}
int dyn_mu_kind(mu_Command *c) { return c?c->type:0; }
const char *dyn_mu_text(mu_Command *c) { return c && c->type==MU_COMMAND_TEXT?c->text.str:NULL; }
void dyn_mu_rect(mu_Command *c,int *x,int *y,int *w,int *h) {
    mu_Rect rect={0};
    if (c && c->type==MU_COMMAND_RECT) rect=c->rect.rect;
    else if (c && c->type==MU_COMMAND_CLIP) rect=c->clip.rect;
    else if (c && c->type==MU_COMMAND_ICON) rect=c->icon.rect;
    else if (c && c->type==MU_COMMAND_TEXT) rect=mu_rect(c->text.pos.x,c->text.pos.y,0,0);
    *x=rect.x;*y=rect.y;*w=rect.w;*h=rect.h;
}
unsigned dyn_mu_color(mu_Command *c) {
    mu_Color color={0};
    if (c && c->type==MU_COMMAND_RECT) color=c->rect.color;
    else if (c && c->type==MU_COMMAND_TEXT) color=c->text.color;
    else if (c && c->type==MU_COMMAND_ICON) color=c->icon.color;
    return ((unsigned)color.r<<24)|((unsigned)color.g<<16)|((unsigned)color.b<<8)|color.a;
}
int dyn_mu_icon(mu_Command *c) { return c && c->type==MU_COMMAND_ICON?c->icon.id:0; }
void dyn_mu_scroll(DynUi *s,int x,int y) {
    if (!s || s->active || x<-30000 || x>30000 || y<-30000 || y>30000) return;
    /* Bound accumulated input too, including a long event queue. */
    if (s->ui.scroll_delta.x+x<-1000000 || s->ui.scroll_delta.x+x>1000000 || s->ui.scroll_delta.y+y<-1000000 || s->ui.scroll_delta.y+y>1000000) return;
    mu_input_scroll(&s->ui,x,y);
}

bool dyn_mu_ready(DynUi *s) { return s && s->ready && !s->active; }

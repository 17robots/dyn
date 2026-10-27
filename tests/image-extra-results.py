#!/usr/bin/env python3
"""BMP/TGA/GIF/JPEG goldens, external decode oracles, malformed input and cross-targets."""
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
CLI='''use "std/image/FORMAT" codec
use "std/mem" mem
use "std/fs" fs
use "std/process" process
use "std/io" io
use "std/strings" strings
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  args := process.arguments(&arena)
  if !args.ok || #len(args.value) != 4 { #panic("image arguments") }
  ENCODER
  source := fs.read_all(&arena, args.value[2], 64000000)
  if !source.ok { #panic("image source") }
  before := mem.arena_mark(&arena)
  result := codec.decode(&arena, source.value)
  if !result.ok {
    if mem.arena_mark(&arena) != before { #panic("image rollback") }
    _ = io.println(io.stdout(), "ERR {}", #cast(u32, result.kind))
    return
  }
  if !fs.write_all(args.value[3], result.value.pixels).ok { #panic("image output") }
  _ = io.println(io.stdout(), "{} {}", result.value.info.width, result.value.info.height)
}
'''
ENCODER='''if strings.starts_with(args.value[1], "encode") {
  channels := strings.parse(u8, args.value[1][6..])
  pixels: [16]u8 = []
  for i in 0..4 { for j in 0..#cast(usize, channels) { pixels[i * #cast(usize, channels) + j] = #cast(u8, (i * 51 + j * 37)) } }
  result := codec.encode(&arena, pixels[..4 * #cast(usize, channels)], 2, 2, channels)
  if !result.ok || !fs.write_all(args.value[2], result.value).ok { #panic("image encode") }
  return
}'''
u16=lambda x:struct.pack('<H',x)
u32=lambda x:struct.pack('<I',x)
def bmp(width,height,bits,raster,palette=b'',compression=0,masks=b'',dib=40):
    offset=14+dib+len(masks)+len(palette)
    header=struct.pack('<IiiHHIIiiII',dib,width,height,1,bits,compression,len(raster),0,0,len(palette)//4,0)
    return b'BM'+u32(offset+len(raster))+b'\0'*4+u32(offset)+header+b'\0'*(dib-40)+masks+palette+raster

def tga(width,height,bits,raster,kind=2,descriptor=32,id=b''):
    return bytes([len(id),0,kind])+b'\0'*9+u16(width)+u16(height)+bytes([bits,descriptor])+id+raster

def gif_literal(indices,width,height,interlaced=False,transparent=None,local=False,left=0,top=0,screen=None):
    # Every pixel starts with CLEAR, a deliberately simple independent bitstream.
    codes=[]
    for index in indices:codes.extend((4,index))
    codes.append(5)
    accumulator=0;count=0;packed=bytearray()
    for code in codes:
        accumulator|=code<<count;count+=3
        while count>=8:packed.append(accumulator&255);accumulator>>=8;count-=8
    if count:packed.append(accumulator&255)
    blocks=b''.join(bytes([len(packed[i:i+255])])+packed[i:i+255] for i in range(0,len(packed),255))+b'\0'
    palette=bytes([255,0,0,0,255,0,0,0,255,255,255,255])
    sw,sh=screen or (width,height)
    header=b'GIF89a'+u16(sw)+u16(sh)+bytes([0 if local else 0x81,0,0])+(b'' if local else palette)
    gce=b'' if transparent is None else b'!\xf9\x04\x01\0\0'+bytes([transparent])+b'\0'
    return header+gce+b','+u16(left)+u16(top)+u16(width)+u16(height)+bytes([(64 if interlaced else 0)|(0x81 if local else 0)])+(palette if local else b'')+b'\x02'+blocks+b';'

def rgba(rgb):return b''.join(rgb[i:i+3]+b'\xff' for i in range(0,len(rgb),3))
def parse_pnm(data):
    at=0;tokens=[]
    while len(tokens)<4:
        while data[at] in b' \r\n\t':at+=1
        if data[at]==35:
            at=data.index(10,at)+1;continue
        start=at
        while data[at] not in b' \r\n\t':at+=1
        tokens.append(data[start:at])
    return tokens,data[at+1:]

with tempfile.TemporaryDirectory(prefix='dyn-image-extra-') as directory:
    work=Path(directory);programs={}
    for kind in ('bmp','tga','gif','jpeg'):
        project=work/kind;project.mkdir()
        (project/'main.dyn').write_text(CLI.replace('FORMAT',kind).replace('ENCODER',ENCODER if kind in ('bmp','tga') else ''))
        for mode in ('debug','release'):
            output=work/(kind+'-'+mode)
            subprocess.run([DYN,'build',str(project),'--'+mode,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
            programs[kind,mode]=output
    number=0
    def decode(kind,data,expected=None,dimensions=None,tolerance=0):
        global number
        number+=1;source=work/f'input-{number}';source.write_bytes(data)
        for mode in ('debug','release'):
            output=work/'pixels'
            ran=subprocess.run([str(programs[kind,mode]),'decode',str(source),str(output)],capture_output=True,text=True,timeout=30)
            assert ran.returncode==0,(kind,mode,ran.stdout,ran.stderr)
            if expected is False:
                assert ran.stdout.startswith('ERR '),(kind,ran.stdout)
            elif expected is not None:
                assert not ran.stdout.startswith('ERR '),(kind,ran.stdout)
                if dimensions:assert tuple(map(int,ran.stdout.split()))==dimensions,(kind,ran.stdout)
                pixels=output.read_bytes();assert len(pixels)==len(expected)
                assert max((abs(a-b) for a,b in zip(pixels,expected)),default=0)<=tolerance,(kind,mode,max(abs(a-b) for a,b in zip(pixels,expected)))
        return source
    colors=bytes([255,0,0,0,255,0,0,0,255,255,255,255]);expected=rgba(colors)
    bgr=lambda pixels:b''.join(pixels[i:i+3][::-1] for i in range(0,len(pixels),3))
    basic=bmp(2,2,24,bgr(colors[6:])+b'\0\0'+bgr(colors[:6])+b'\0\0')
    decode('bmp',basic,expected,(2,2))
    decode('bmp',bmp(2,-2,24,bgr(colors[:6])+b'\0\0'+bgr(colors[6:])+b'\0\0'),expected,(2,2))
    palette=b''.join(colors[i:i+3][::-1]+b'\0' for i in range(0,12,3))
    decode('bmp',bmp(2,2,4,b'\x23\0\0\0\x01\0\0\0',palette),expected,(2,2))
    decode('bmp',bmp(2,2,8,b'\x02\x03\0\0\x00\x01\0\0',palette),expected,(2,2))
    decode('bmp',bmp(2,1,1,b'\x40\0\0\0',palette[:8]),expected[:8],(2,1))
    masks=u32(0xf800)+u32(0x7e0)+u32(0x1f)
    decode('bmp',bmp(2,1,16,u16(0xf800)+u16(0x7e0),compression=3,masks=masks),expected[:8],(2,1))
    for descriptor in (0,16,32,48):
        rows=[colors[:6],colors[6:]]
        if not descriptor&32:rows=rows[::-1]
        if descriptor&16:rows=[row[3:]+row[:3] for row in rows]
        decode('tga',tga(2,2,24,bgr(b''.join(rows)),descriptor=descriptor,id=b'example'),expected,(2,2))
    decode('tga',tga(2,2,24,b'\x03'+bgr(colors),kind=10),expected,(2,2))
    decode('tga',tga(2,2,24,b'\x83\0\0\xff',kind=10),bytes([255,0,0,255])*4,(2,2))
    decode('tga',tga(2,1,16,bytes([30,80,200,255]),kind=3,descriptor=40),bytes([30,30,30,80,200,200,200,255]),(2,1))
    decode('gif',gif_literal([0,1,2,3],2,2),expected,(2,2))
    decode('gif',gif_literal([0,1,2,3],2,2,local=True),expected,(2,2))
    decode('gif',gif_literal([0,1,2,3],2,2,transparent=1),expected[:4]+b'\0'*4+expected[8:],(2,2))
    rows=[[i%4]*3 for i in range(9)]
    interlaced=[row for start,step in ((0,8),(4,8),(2,4),(1,2)) for row in rows[start::step]]
    palette_rgb=[bytes([255,0,0,255]),bytes([0,255,0,255]),bytes([0,0,255,255]),bytes([255,255,255,255])]
    decode('gif',gif_literal([p for row in interlaced for p in row],3,9,True),b''.join(palette_rgb[p] for row in rows for p in row),(3,9))
    for kind,source in (('bmp',basic),('tga',tga(2,2,24,bgr(colors))),('gif',gif_literal([0,1,2,3],2,2))):
        # GIF has a first-image API: the trailer is intentionally not required.
        end=len(source)-1 if kind=='gif' else len(source)
        for length in range(end):decode(kind,source[:length],False)
        rng=random.Random(0x1324)
        for _ in range(30):
            mutant=bytearray(source);at=rng.randrange(len(mutant));mutant[at]^=1<<rng.randrange(8);decode(kind,bytes(mutant))
    def jpeg_minimal(allones=False,padding=0x3f):
        segment=lambda marker,payload:bytes([255,marker])+struct.pack('>H',len(payload)+2)+payload
        dc=bytes([0,2 if allones else 1])+bytes(15)+bytes([0])+ (bytes([1]) if allones else b'')
        ac=bytes([16,1])+bytes(15)+bytes([0])
        return b'\xff\xd8'+segment(219,b'\0'+bytes([1])*64)+segment(192,bytes([8,0,1,0,1,1,1,17,0]))+segment(196,dc+ac)+segment(218,bytes([1,1,0,0,63,0]))+bytes([padding])+b'\xff\xd9'
    decode('bmp',bmp(2,2,24,b'\0'*16,dib=64),False)
    decode('jpeg',jpeg_minimal(),bytes([128,128,128,255]),(1,1))
    decode('jpeg',jpeg_minimal(allones=True),False)
    decode('jpeg',jpeg_minimal(padding=0),False)
    # Independent encoders/decoders provide additional standard-format oracles.
    if shutil.which('ffmpeg'):
        for kind in ('bmp','tga'):
            for channels in ((3,4) if kind=='bmp' else (1,2,3,4)):
                path=work/f'encoded-{kind}-{channels}.{kind}'
                subprocess.run([str(programs[kind,'release']),f'encode{channels}',str(path),'ignored'],check=True,timeout=30)
                raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','rgba','-'],capture_output=True,check=True,timeout=30).stdout
                samples=[bytes((i*51+j*37)&255 for j in range(channels)) for i in range(4)]
                golden=b''.join((p[:1]*3 if channels<3 else p[:3])+(p[-1:] if channels in (2,4) else b'\xff') for p in samples)
                if not (kind=='tga' and channels==2): assert raw==golden,(kind,channels,raw,golden) # FFmpeg interprets 16-bit grayscale TGA as RGB555.
                decode(kind,path.read_bytes(),golden,(2,2))
        # Real GIF LZW streams grow from 9 through 12 bits and fill dictionaries.
        rng=random.Random(42);rgb=bytes(rng.randrange(256) for _ in range(64*64*3))
        ppm=work/'random.ppm';ppm.write_bytes(b'P6\n64 64\n255\n'+rgb)
        gif=work/'random.gif'
        subprocess.run(['ffmpeg','-v','error','-i',str(ppm),'-frames:v','1','-vf','format=rgb8',str(gif)],check=True,timeout=30)
        oracle=subprocess.run(['ffmpeg','-v','error','-i',str(gif),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','-'],capture_output=True,check=True,timeout=30).stdout
        decode('gif',gif.read_bytes(),oracle,(64,64))
    else:print('SKIP optional FFmpeg image oracles')
    if shutil.which('cjpeg') and shutil.which('djpeg'):
        w,h=19,17;rgb=bytes((x*13+y*17+c*61)%256 for y in range(h) for x in range(w) for c in range(3))
        ppm=work/'photo.ppm';ppm.write_bytes(f'P6\n{w} {h}\n255\n'.encode()+rgb)
        scans=work/'scans';scans.write_text('0;\n1;\n2;\n')
        for options in ([],['-sample','1x1'],['-sample','2x1'],['-restart','1B'],['-grayscale'],['-rgb'],['-scans',str(scans)],['-optimize']):
            jpeg=work/'photo.jpg'
            subprocess.run(['cjpeg','-quality','91',*options,'-outfile',str(jpeg),str(ppm)],check=True,timeout=30)
            oracle=subprocess.run(['djpeg','-dct','float','-nosmooth','-rgb',str(jpeg)],capture_output=True,check=True,timeout=30).stdout
            tokens,pixels=parse_pnm(oracle);assert tokens[0]==b'P6'
            decode('jpeg',jpeg.read_bytes(),rgba(pixels),(w,h),2)
        data=jpeg.read_bytes()
        for length in range(0,len(data),max(1,len(data)//80)):decode('jpeg',data[:length],False)
        rng=random.Random(5)
        for _ in range(80):
            mutant=bytearray(data);at=rng.randrange(len(mutant));mutant[at]^=1<<rng.randrange(8);decode('jpeg',bytes(mutant))
        subprocess.run(['cjpeg','-progressive','-outfile',str(jpeg),str(ppm)],check=True,timeout=30)
        decode('jpeg',jpeg.read_bytes(),False)
    else:print('SKIP optional libjpeg JPEG oracles')
    fixture_data={'bmp':basic,'tga':tga(2,2,24,bgr(colors)),'gif':gif_literal([0,1,2,3],2,2)}
    if shutil.which('cjpeg'):fixture_data['jpeg']=data
    for kind,fixture in fixture_data.items():
        project=work/(kind+'-portable');project.mkdir()
        source='use "std/image/'+kind+'" codec\nuse "std/mem" mem\nfn main() { arena := mem.Arena{}; defer { mem.arena_release(&arena) }; source: ['+str(len(fixture))+']u8 = ['+','.join(map(str,fixture))+']; result := codec.decode(&arena,source[..]); if !result.ok || result.value.info.width == 0 { #panic("portable image") } }'
        (project/'main.dyn').write_text(source.replace('; ', '\n'))
        for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
            subprocess.run([DYN,'build',str(project),'--release','--target',target,'--quiet','--output',str(work/(kind+'-'+target))],check=True,timeout=300)
            executable=str(work/(kind+'-'+target))
            command=None
            if target=='aarch64-linux' and shutil.which('qemu-aarch64'):command=['qemu-aarch64',executable]
            if target=='riscv64-linux' and shutil.which('qemu-riscv64'):command=['qemu-riscv64',executable]
            if target=='wasm32-wasi' and shutil.which('node'):
                js="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',args:[],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance)})().catch(e=>{console.error(e);process.exit(1)})"
                command=['node','--no-warnings','-e',js,executable]
            if command:subprocess.run(command,check=True,timeout=30)
print(f'PASS extra image codecs: {number} golden/truncation/mutation cases in debug/release; cross-builds and independent FFmpeg/libjpeg oracles')

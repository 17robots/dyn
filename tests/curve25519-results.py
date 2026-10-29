#!/usr/bin/env python3
"""RFC7748/8032 plus independent OpenSSL-backed curve and hashlib oracles."""
import hashlib,os,random,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
def literal(b):return '"'+''.join('\\x%02x'%x for x in b)+'"'
s='''use "std/crypto/x25519" x
use "std/crypto/ed25519" ed
use "std/crypto/exchange" exchange
use "std/crypto/signature" signature
use "std/crypto/sha512" sha
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("curve contract") } }
fn hash(message: []const u8,expected: []const u8) {
 output: [64]u8
 check(bytes.equal(sha.digest(output[..],message),expected))
 for split in 0..#len(message)+1 {
  state:=sha.init()
  check(sha.update(&state,message[..split]) && sha.update(&state,"") && sha.update(&state,message[split..]))
  check(bytes.equal(sha.finish(&state,output[..]),expected))
 }
}
fn curve(private: []const u8,peer: []const u8,public: []const u8,secret: []const u8) {
 output: [40]u8
 for i in 0..40 { output[i]=165 }
 check(exchange.x25519_public(output[..],private).ok && bytes.equal(output[..32],public))
 check(exchange.x25519(output[..],private,peer).ok && bytes.equal(output[..32],secret))
 for i in 32..40 { check(output[i]==165) }
 zero: [32]u8
 check(!exchange.x25519(output[..],private,zero[..]).ok)
 for i in 0..32 { check(output[i]==0) }
 for i in 32..40 { check(output[i]==165) }
}
fn sign(key: []const u8,message: []const u8,public: []const u8,expected: []const u8) {
 output: [72]u8
 for i in 0..72 { output[i]=165 }
 check(signature.ed25519_public(output[..],key).ok && bytes.equal(output[..32],public))
 check(signature.ed25519_sign(output[..],message,key).ok && bytes.equal(output[..64],expected))
 check(ed.valid_public_key(public))
 check(signature.ed25519_verify(output[..64],message,public))
 for i in 64..72 { check(output[i]==165) }
 for i in 0..64 {
  output[i]^=1
  check(!signature.ed25519_verify(output[..64],message,public))
  output[i]^=1
 }
}
fn main() {
'''
rng=random.Random(77488032)
# RFC8032 test1.
key=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
# Offline cryptography/OpenSSL oracle outputs; no third-party test dependency.
ED_GOLDENS=[('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', 'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'), ('c1b2a7017afef15fe0cdbcf4c300e7917e4ba9985050fbc2aa5ca9ba8d6cebcf', '545a45b0d9489153263fa8a4c54f6285c005482858446636a4bd9f7dc5b61ee488c9647e8148740e01c6cdd68c5af7b08bb7c95b8fa5896e14ab1080ee2f5105'), ('98f19cbc77a2d330f128490b0df4e0e9fd3362e0fbc8832e6e0255d814a7330f', '939759c3ad40d42686647ffad468ff053a3921ea890c6336e7f288a03bac689f254018f4776f3c441f88ab668869435f1a37e2b8af03f5f8356cf65356ac1e00'), ('098790047eddfc73053962d3010fd93963bf5865c4e3114ded673519f934884c', '3714049ca602f1a951ab05ef3e260434108699803c6485c4835653ba64e1547aad8dc999292c02b42d373f5df547331754c33611f331ffccc66cea4351e92308'), ('9207fcc6cd49a18c1823800aee283f02ea9d485012b1ccdc39ab90ad17c3dcf0', '717837c64aa1e4f7ba0597c609cb9dd3d6986428bc2f79e8587397b2afdd211a884ac46ba84443d915cdcacbeed8542808b4418dbc4bcebc12ca2bb1ba0c0408'), ('2cadd72c700d41a68d9e22a81c4451113ede18e59e18cc1c0a0b7a94ba1b9826', '04270895e5cc2fabdfd22bbe7674bed6dcb631147c2f59875a9dd281caf25c032cd05be8a43c50a75f10fa9c73b5cbaeadfeae0208655087ce9ab96f308e3c0c'), ('6bfba1418ad350cd92bc3056c774548f13ba94b8b0c711ba6ea8544660a43a64', 'e6734ce898c2e7b40ce0fbde82d56c5d52c280c1a719b8cecb88c5370f681305231e5ec5a49debb2f0f0c6eedf345259e769ed6f153a16f9c355eecaf5b91b07'), ('51c516ec1a665b1fdf48a17654c437484cd64a0284cb3f50fd72b181f937be73', '39b6e6a296e6ab1f42fafb56a41b23d709d192bf0b0677024e96b1bbfca1698f311cb24ea8ee97cd133e33ac6b20a767128ac164c97fd5993c8093c6e741670f'), ('b4dfc87f54e4c76e75db0bca619857ec1e7d467aed983c55334ab2b47d5c713e', 'd6df379f314febdb0fac3ccb09c1939194e0fcc0577b597857b7fe029daf8ccbc8ab9f357f7979342057b13a883b3b8b7594fa7328bf6d32bb65252441682d03'), ('099da47c1e9a0b584bcb1a867051b72bbb918bd8b7155be8d7e0432994e0f6cf', '0c48edfad4bb738c48d4aa560b3cd839e006fab07e7cf7d60cdca94a7a8f5cdd76e80f307923da37d1fa3bd5f216487446b3d1e7659477e770762b616a55b506'), ('957644bd7292ef26710adb97f9b964c8e1ca9075ef3744e44a80fe5fceb1f76b', 'eaf1a85b57b39c0314bd6d55e741fcce368058e77ea51418bd88143ef376bab03c70da98bec5a49d406f38aa690aa26bd91f006a8e35a0ee4869f08ca1340804'), ('84c951ca8770d62b93dd08bf9a192ce221749fca89547bf84e80774117b45bea', '22be8d9037d7ef18742da3fe882e938bf4aef4f07cc6789323c52dd120dd5acbfa4ce463974af5827e3c6cbb795447583134d4eba3b952cf8a3504aa0e2e8a00'), ('9e3a550b71ff818b7c7ce9874a1339eeff38833fe031b2f8b7e8c07ef60c4195', 'b8cd49864a6a3cc26f73bc51c43bed3598c9f8d7467ed953707dc1759d368ee5135a7b00b1da9efd1b3e812be75c5d8d0b571d298fddae304bb595517ec8d203'), ('b0a2256d9ff548f52fabee2485ca1e309728b79ee3ab52c9d38823b5298b649c', '01791e4ec087d2ba6314744102a10c716539e6a4490b3987849a643d4c90437a5adfaf58adb7bc91c7aa24dc4bd905ab54949c213611da38b54b85ccb7c94e07'), ('3b70011ff20998598c7c8ce2d3ad0f0e06b11bdead066571b410bd4d652b7d1f', 'a6a6d29b67945dc7d53544356778f092ee6e92b6c936ac27d7e46ab639c0ba9d47f3091e6b9f3d7182f5365929d0f13035efdcf3b11ac7419edd86b0c1749105')]
X_GOLDENS=[('32d0f58efeb07f9051ce27b1b884bc4528c471b3e5a189d14e4ca2d2cd310472', 'e1b2d571053d4086757f6321d169f45dabb7bea5e2cb441c33e10ee55242f31c', '95a4fa213dcfee735cba95d79c9a39ff75339d196133066d1efbb1fd8bb0c57c'), ('b53d39ed7c8fac13d1f4f5e8c585cdcfa291dd25d098f743bbf80a56794d926d', '83ca8e8a50612bf273dae008a4346e69ba12a67906f6c6a2f05d32b897fbbc72', '246efb6eff42f91f9d25685f2b6429aa459889faa547baa234e12609c58e505b'), ('02dae3b6a60cdd5c4f7810ba255603d5c1e275bbbbe3f47c3bd38065ab582f66', '76a6f9abcec872c98dc37ead0c08023b49dbe02a1305cabebe3f1fe8be7f8373', 'ff247e39596804ce8cedb0055238fbb0150d09d872efcce48823f1f4d3070543'), ('cae6a51ac8ed316a0902d420891a0c4b78b5edc6b2d041f302f039408e06ea3f', '17034f8efa8edb396f2b75af2fd5328e0973e40cd6e19dbf2127e6b4cecfa367', '9cebbd459d9836dba32d87b325fbde5d390a62182ce6c1267f66efec51c1370f'), ('827d0ad5e610696a98596411adaa03f4d091d06951d02e75a90cfe54e6660c67', '8582e2583ede803f0f5bfe54ab75ba7bd0aafe7ca065329d915aaf07304bd26a', '6bc8e5b81484550f78631d89da7946f2d8ee4c2358ddd0253d1c0a6d72e34f57'), ('f42f9db218af9d0a8c21112813286bb74b9058b5569c0b412596cfb661899f25', 'a6bc6f9a80bbcae5dc0628a5b7b03cb070103b963e25d72f4ad61ae8e0fe8416', 'ee9f657a1e61709888465f37237eedf82ea67677f7c73688e91e312f76316f7d'), ('59dd700ddc207d6da2421042d47524faccda79bfdc1d703819c4eb6f4464076c', '2d53612d73cebdf9f61da363f5ed5d7e7bbdfc7fe8f0191bc93806f9fa1eee40', 'bd203dd7e2a0379a9a9a517d6aedb2694b22bf5ce2750738d31d5991aba9dc2d'), ('a3782aa917e89f2709844b874609ee05d1394f420a09e291fa2b4a8c57f9c010', 'c64ea9ff6299cc3923b8e7a25b70bc8466c1b54d275cd6d126938453b79bfb01', 'df32d476db69b0c85c6ab6ae837b5d84b08f3515e0e583ada3e328634788ba5d'), ('0e8a3ec080c6e98bc8a29004faa4c29f947a609bbfaad54b5ed4ce014bc8421a', 'ff994f61c2c93757fd1601c4fa009b9ad55d227c7c2a4ccd79d2cda41e16395d', '734cc4f404cd7b17c91bca394405467059e3bd499f7ed7e7bc506c6b7b50cc4c'), ('4cf03b150328e0502d347e116c9769ea8e55e64b1edc51c394ba52dfbb0e0f53', '90200d39415da31c8170c2d40cf60242ea7b31e538b3050cb5441f7237edd970', '90f5ef87a242a36dc2e6f0b68e1bf463120fa49a8fb803f5b1093dc9eec73647'), ('b81954d96a4e140ec91158369a92e3bb66308065057524d9c2198f7d3cc44a09', 'dcd0c731eaed2c1d2dfc55ff05c9dad2475274bdccde241a215d4ce66dffa37c', '6323b9992e65aebeaf1617cf33a731df2ca2dff739b554725933dd28ce07bb13'), ('6e4740f1fd49ccfa549fcd1173eed415c8d3513c004e28dd8396a17e70fb231f', 'fa347fe1085a74a3f84f328eb1952637d174836536e2190077e4978d75de0d5b', '3250d1d9b774464be8e083a2fd00b0e460117b6546b5c13fd6b10f3c1f954f67'), ('9acd1df9553337ba6feb7a6f55cec332808e81fb29ff9df1b4db0c75b62fd625', 'dd99d15a50ec0b766c036177fee842086aeb980c2f752dab24e07a0a4ea3f941', '9c6efb07677d1578d070e2e3051d165fc8212aff3c32cf2398224ac7a8960907'), ('fc6b8cbb62f81ba7f67d560ab08a69675b12685ca9cb3e3eef87f49b21231112', '0c25f516fdacb8c28af3dfbe3ad2fd1ef172617e94f33fd2e4f19780fb54c026', '4c90f63f6f87929fd2df1f604b0137049b338c8fccffdb61dc200cb9a9c6af35'), ('7dcac4fd9bba40f6f0fff8ff5ca039b4cbcb3d7bda1132e46e60465979e52a4c', '7a77210162edfd664c68af6ecace798385b90e1308bc708506ba9e872a2b6e08', '9da0a13854da11c1c175efcd36c656e1c2e690ee6c5da527ad7ea5984159b711'), ('1dcdc19d3d39997c157b0284aa8876e390fbc03bb391587c50e0f0453d7a951a', '8b4c791d3c580dd90bd0b46844b6fd0414d17c0bc540d830fe633651635aa33f', '55f2f98e4162e65cd2d37041355ba833e942dd7b030953698ac6bbd68c078f41')]
for index,(key,message) in enumerate([(key,b'')]+[(rng.randbytes(32),rng.randbytes(n)) for n in [1,15,16,31,32,63,64,111,112,127,128,129,255,1024]]):
 public,signature=map(bytes.fromhex,ED_GOLDENS[index])
 s+=' sign('+','.join(map(literal,[key,message,public,signature]))+')\n'
for n in [0,1,111,112,127,128,129,255,256,257,1024]:
 message=rng.randbytes(n)
 s+=' hash('+literal(message)+','+literal(hashlib.sha512(message).digest())+')\n'
# RFC7748 Alice public key and Alice/Bob shared secret.
rfc=[bytes.fromhex(value) for value in (
 '77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a',
 'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f',
 '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a',
 '4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742')]
s+=' curve('+','.join(map(literal,rfc))+')\n'
for index in range(16):
 key,peer=rng.randbytes(32),rng.randbytes(32)
 peer_public,public,shared=map(bytes.fromhex,X_GOLDENS[index])
 s+=' curve('+','.join(map(literal,[key,peer_public,public,shared]))+')\n'
s+=''' key: [32]u8
 output: [96]u8
 check(!exchange.x25519_public(output[..],output[64..96]).ok)
 check(!signature.ed25519_sign(output[..],output[80..81],key[..]).ok)
 check(!signature.ed25519_public(output[..31],key[..]).ok)
 identity: [32]u8
 identity[0]=1
 signature_bytes: [64]u8
 signature_bytes[0]=1
 check(!ed.valid_public_key(identity[..]) && !ed.valid_public_key(key[..]))
 check(!ed.valid_public_key(key[..31]))
 check(!ed.verify(signature_bytes[..],"",identity[..]))
 check(!ed.verify(signature_bytes[..63],"",key[..]))
}\n'''
with tempfile.TemporaryDirectory(prefix='dyn-curves-') as directory:
 work=Path(directory);(work/'main.dyn').write_text(s)
 for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
  output=work/'program'
  subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
  subprocess.run([str(output)],check=True,timeout=120)
 for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
  output=work/target
  subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
  emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
  if emulator and shutil.which(emulator):subprocess.run([emulator,str(output)],check=True,timeout=180)
  if target=='wasm32-wasi' and shutil.which('node'):
   script="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
   subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=180)
print('PASS native X25519, Ed25519, SHA512: independent vectors, streaming, rejection, cross-targets')

## oo_judge

created by gf, lzq, wty, xxk.

使用时，将打包好的源代码放到 zip 文件夹下，当 jar 文件夹下没有 jar 文件时，会自动从 zip 文件夹下获取源码并编译。

对于 unit_2 等单元，如果需要加官方投喂包等引用的类的话，放到某一路径下，并按照 example/config.yml 所示配置该路径。packaging.py 会自动将投喂包打包进编译好的 jar 包。
